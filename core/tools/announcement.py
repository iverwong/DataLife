"""公告查询 LangGraph 工具集。

面向 LLM 的三个工具：搜索、grep、读取。
后台自动处理 API 调用、PDF 下载、解析和缓存。
"""

from datetime import date

from langchain_core.tools import tool  # pyright: ignore[reportUnknownVariableType]

from core.tools.services.announcement_cache import AnnouncementCache
from core.tools.services.cninfo_client import CninfoClient
from core.tools.services.types import (
    AnnouncementInfo,
    CategoryName,
    GrepInput,
    GrepMatch,
    ReadInput,
    SearchInput,
)


# ── 数据结构───────────────────────────────────────────────────────────────


from dataclasses import dataclass


@dataclass(frozen=True)
class _MergedInterval:
    """合并后的上下文区间。

    Attributes:
        start_line: 区间起始行号（含，从 1 开始）。
        end_line:   区间结束行号（含，从 1 开始）。
        match_lines: 区间内所有命中行号的集合。
        lines:       区间内所有行的文本内容（按顺序）。
    """

    start_line: int
    end_line: int
    match_lines: frozenset[int]
    lines: tuple[str, ...]


def _build_merged_intervals(
    matches: list[GrepMatch],
    before: int,
    after: int,
    all_lines: list[str],
) -> list[_MergedInterval]:
    """将命中行及其上下文合并为不重叠的连续区间。

    Args:
        matches:   grep 返回的原始命中列表（已按行号升序排列）。
        before:    每条命中前置上下文行数。
        after:     每条命中后置上下文行数。
        all_lines: 公告全文按行分割的列表（0-indexed）。
    Returns:
        按顺序排列的合并区间列表。
    """
    if not matches:
        return []

    total = len(all_lines)

    # 计算每条命中的裸区间 [start, end]（1-indexed，含）
    raw: list[tuple[int, int, int]] = []  # (start, end, match_line)
    for m in matches:
        s = max(1, m.line_number - before)
        e = min(total, m.line_number + after)
        raw.append((s, e, m.line_number))

    # 按 start 排序后合并相邻/重叠区间
    raw.sort(key=lambda x: x[0])
    merged_ranges: list[tuple[int, int, list[int]]] = []
    cur_s, cur_e, cur_matches = raw[0]
    cur_match_lines: list[int] = [cur_matches]

    for s, e, ml in raw[1:]:
        if s <= cur_e + 1:  # 重叠或相邻
            cur_e = max(cur_e, e)
            cur_match_lines.append(ml)
        else:
            merged_ranges.append((cur_s, cur_e, cur_match_lines))
            cur_s, cur_e = s, e
            cur_match_lines = [ml]
    merged_ranges.append((cur_s, cur_e, cur_match_lines))

    # 构建 _MergedInterval，从 all_lines 切取实际文本
    result: list[_MergedInterval] = []
    for s, e, mls in merged_ranges:
        interval_lines = tuple(all_lines[s - 1 : e])  # 0-indexed 切片
        result.append(
            _MergedInterval(
                start_line=s,
                end_line=e,
                match_lines=frozenset(mls),
                lines=interval_lines,
            )
        )
    return result

# ── 模块级单例（lazy init，避免 import 时 NotImplementedError）─────

_client: CninfoClient | None = None
_cache: AnnouncementCache | None = None
_registry: dict[str, AnnouncementInfo] = {}


def _get_client() -> CninfoClient:
    """获取或创建 CninfoClient 单例。"""
    global _client
    if _client is None:
        _client = CninfoClient()
    return _client


def _get_cache() -> AnnouncementCache:
    """获取或创建 AnnouncementCache 单例。"""
    global _cache
    if _cache is None:
        _cache = AnnouncementCache(client=_get_client())
    return _cache


def _register_results(results: list[AnnouncementInfo]) -> None:
    """将搜索结果注册到内存注册表。"""
    for info in results:
        _registry[info.announcement_id] = info


def _resolve(announcement_id: str) -> AnnouncementInfo:
    """从注册表解析公告信息。

    Raises:
        KeyError: 公告未注册（需先调用 search_announcements）。
    """
    if announcement_id not in _registry:
        raise KeyError(
            f"公告 {announcement_id} 未找到，请先使用 search_announcements 搜索"
        )
    return _registry[announcement_id]


def _format_search_results(
    results: list[AnnouncementInfo],
    total: int,
    page: int,
) -> str:
    """将搜索结果格式化为 LLM 可读文本。"""
    if not results:
        return "未找到相关公告"
    lines: list[str] = []
    for info in results:
        lines.append(
            f"id: {info.announcement_id}\n"
            + f"  标题: {info.title}\n"
            + f"  日期: {info.published_date}\n"
            + f"  大小: {info.size_kb}KB\n"
        )
    header = f"共 {total} 条公告，第 {page} 页：\n"
    return header + "\n".join(lines)


def _format_grep_results(
    matches: list[GrepMatch],
    total_lines: int,
    total_matches: int,
    head_limit: int,  # pyright: ignore[reportUnusedParameter]  # truncation happens at caller
    before: int,
    after: int,
    all_lines: list[str],
) -> str:
    """将 grep 结果格式化为 LLM 可读文本（支持区间合并与行号标注）。

    Args:
        matches:       本次格式化的命中列表（已按 head_limit 截断）。
        total_lines:   公告全文总行数。
        total_matches: grep 的全部命中数（截断前）。
        head_limit:    本次展示的上限。
        before:        命中前上下文行数（用于区间合并）。
        after:         命中后上下文行数（用于区间合并）。
        all_lines:     公告全文行列表（用于区间合并时补全行内容）。
    """
    if not matches:
        return "未找到匹配内容"

    intervals = _build_merged_intervals(matches, before, after, all_lines)
    parts: list[str] = []
    for interval in intervals:
        rows: list[str] = []
        for i, line_text in enumerate(interval.lines):
            ln = interval.start_line + i
            prefix = ">>>" if ln in interval.match_lines else "   "
            rows.append(f"{prefix} L{ln}: {line_text}")
        parts.append("--- match ---\n" + "\n".join(rows))

    body = "\n\n".join(parts)
    summary = f"共 {total_matches} 条匹配"
    if len(matches) < total_matches:
        summary += f"，显示前 {len(matches)} 条"
    return f"{summary}\n\n{body}\n\n（全文共 {total_lines} 行）"


# 用户友好名称 → 巨潮 API category 代码
CATEGORY_MAP: dict[str, str] = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
    "业绩预告": "category_yjygjxz_szsh",
    "权益分派": "category_qyfpxzcs_szsh",
    "董事会": "category_dshgg_szsh",
    "监事会": "category_jshgg_szsh",
    "股东会": "category_gddh_szsh",
    "日常经营": "category_rcjy_szsh",
    "公司治理": "category_gszl_szsh",
    "中介报告": "category_zj_szsh",
    "首发": "category_sf_szsh",
    "增发": "category_zf_szsh",
    "股权激励": "category_gqjl_szsh",
    "配股": "category_pg_szsh",
    "解禁": "category_jj_szsh",
    "公司债": "category_gszq_szsh",
    "可转债": "category_kzzq_szsh",
    "其他融资": "category_qtrz_szsh",
    "股权变动": "category_gqbd_szsh",
    "补充更正": "category_bcgz_szsh",
    "澄清致歉": "category_cqdq_szsh",
    "风险提示": "category_fxts_szsh",
    "特别处理和退市": "category_tbclts_szsh",
    "退市整理期": "category_tszlq_szsh",
}


def _resolve_category(category: list[CategoryName] | None) -> str:
    """将用户友好的公告类型列表映射为巨潮 API category 参数。"""
    if not category:
        return ""
    return ";".join(CATEGORY_MAP.get(c, "") for c in category)


@tool(args_schema=SearchInput)
async def search_announcements(
    keyword: str,
    stock_code: str,
    category: list[CategoryName] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = 1,
) -> str:
    """搜索上市公司公告列表，每页 30 条，返回当页结果和总条数。"""
    resolved_category = _resolve_category(category)
    results, total = await _get_client().search(
        stock_code,
        keyword,
        resolved_category,
        start_date,
        end_date,
        page,
    )
    _register_results(results)
    return _format_search_results(results, total, page)


@tool(args_schema=GrepInput)
async def grep_announcement(
    announcement_id: str,
    pattern: str,
    ignore_case: bool = True,
    context_lines: int = 3,
    before_context: int | None = None,
    after_context: int | None = None,
    head_limit: int = 50,
) -> str:
    """在公告全文中用正则表达式搜索，返回命中片段及上下文。"""
    try:
        info = _resolve(announcement_id)
    except KeyError as e:
        return str(e)
    _ = await _get_cache().ensure_cached(info.announcement_id, info.pdf_url)
    matches = _get_cache().grep(
        announcement_id=info.announcement_id,
        pattern=pattern,
        ignore_case=ignore_case,
        context_lines=context_lines,
        before_context=before_context,
        after_context=after_context,
    )
    total_lines = _get_cache().get_total_lines(info.announcement_id)
    total_matches = len(matches)
    before = before_context if before_context is not None else context_lines
    after = after_context if after_context is not None else context_lines
    cache_path = _get_cache()._get_cache_path(info.announcement_id)  # pyright: ignore[reportPrivateUsage]  # design decision: avoid adding public API for this one-off read
    all_lines: list[str] = cache_path.read_text(encoding="utf-8").splitlines()
    return _format_grep_results(
        matches[:head_limit],
        total_lines,
        total_matches,
        head_limit,
        before,
        after,
        all_lines,
    )


@tool(args_schema=ReadInput)
async def read_announcement(
    announcement_id: str,
    offset: int = 1,
    limit: int = 200,
) -> str:
    """读取公告全文的指定范围。"""
    try:
        info = _resolve(announcement_id)
    except KeyError as e:
        return str(e)
    _ = await _get_cache().ensure_cached(info.announcement_id, info.pdf_url)
    return _get_cache().read_lines(info.announcement_id, offset, limit)
