"""公告查询 LangGraph 工具集。

面向 LLM 的三个工具：搜索、grep、读取。
后台自动处理 API 调用、PDF 下载、解析和缓存。
"""

from __future__ import annotations

from datetime import date

from langchain_core.tools import tool  # pyright: ignore[reportUnknownVariableType]

from core.tools.services.announcement_cache import AnnouncementCache
from core.tools.services.cninfo_client import CninfoClient
from core.tools.services.types import (
    AnnouncementInfo,
    GrepInput,
    GrepMatch,
    ReadInput,
    SearchInput,
)

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


def _parse_date_range(
    date_range: str,
) -> tuple[date | None, date | None]:
    """解析日期范围字符串 'YYYY-MM-DD~YYYY-MM-DD'。

    空字符串返回 (None, None)。
    """
    if not date_range:
        return None, None
    parts = date_range.split("~")
    if len(parts) != 2:
        return None, None
    start = date.fromisoformat(parts[0].strip())
    end = date.fromisoformat(parts[1].strip())
    return start, end


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
    head_limit: int,
) -> str:
    """将 grep 结果格式化为 LLM 可读文本。"""
    if not matches:
        return "未找到匹配内容"
    parts: list[str] = []
    for m in matches:
        ctx_before = "\n".join(f"  {c}" for c in m.context_before)
        ctx_after = "\n".join(f"  {c}" for c in m.context_after)
        parts.append(
            f"--- Line {m.line_number} ---\n"
            + f"{ctx_before}\n"
            + f">>> {m.content} <<<\n"
            + f"{ctx_after}"
        )
    body = "\n\n".join(parts)
    truncated = ""
    if len(matches) >= head_limit:
        truncated = f"\n\n（仅显示前 {head_limit} 条匹配结果）"
    return f"{body}\n\n（全文共 {total_lines} 行）{truncated}"


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


def _resolve_category(category: list[str] | None) -> str:
    """将用户友好的公告类型列表映射为巨潮 API category 参数。"""
    if not category:
        return ""
    return ";".join(CATEGORY_MAP.get(c, "") for c in category)


@tool(args_schema=SearchInput)
async def search_announcements(
    keyword: str,
    stock_code: str,
    category: list[str] | None = None,
    date_range: str = "",
    page: int = 1,
) -> str:
    """搜索上市公司公告列表，每页 30 条，返回当页结果和总条数。"""
    start_date, end_date = _parse_date_range(date_range)
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
    return _format_grep_results(matches[:head_limit], total_lines, head_limit)


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
