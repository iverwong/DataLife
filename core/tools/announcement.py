"""公告查询 LangGraph 工具集。

面向 LLM 的三个工具：搜索、grep、读取。
后台自动处理 API 调用、PDF 下载、解析和缓存。
"""

from __future__ import annotations

from datetime import date

from langchain_core.tools import tool

from core.tools.services.announcement_cache import AnnouncementCache
from core.tools.services.cninfo_client import CninfoClient
from core.tools.services.types import (
    AnnouncementInfo,
    GrepMatch,
    GrepInput,
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
            f"公告 {announcement_id} 未找到，"
            "请先使用 search_announcements 搜索"
        )
    return _registry[announcement_id]


def _parse_date_range(
    date_range: str,
) -> tuple[date | None, date | None]:
    """解析日期范围字符串 'YYYY-MM-DD~YYYY-MM-DD'。

    空字符串返回 (None, None)。
    """
    raise NotImplementedError


def _format_search_results(
    results: list[AnnouncementInfo],
    total: int,
    page: int,
) -> str:
    """将搜索结果格式化为 LLM 可读文本。

    包含当页公告列表 + 分页信息（总 {total} 条，当前第 {page} 页）。
    """
    raise NotImplementedError


def _format_grep_results(
    matches: list[GrepMatch],
    total_lines: int,
    head_limit: int,
) -> str:
    """将 grep 结果格式化为 LLM 可读文本。

    若 head_limit 截断了结果，末尾附提示。
    """
    raise NotImplementedError


def _resolve_category(category: list[str] | None) -> str:
    """将用户友好的公告类型列表映射为巨潮 API category 参数。

    将 ["年报", "半年报"] → "category_ndbg_szsh;category_bndbg_szsh"。
    None 或空列表返回 ""（不限类型）。

    注意：因已有 Pydantic SearchInput 的 Literal 校验，
    此处不需要再做值域检查，直接查表即可。
    """
    raise NotImplementedError


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
        stock_code, keyword, resolved_category,
        start_date, end_date, page,
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
    await _get_cache().ensure_cached(info.announcement_id, info.pdf_url)
    matches = _get_cache().grep(
        announcement_id=info.announcement_id,
        pattern=pattern,
        ignore_case=ignore_case,
        context_lines=context_lines,
        before_context=before_context,
        after_context=after_context,
    )
    total_lines = _get_cache().get_total_lines(info.announcement_id)
    return _format_grep_results(
        matches[:head_limit], total_lines, head_limit
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
    await _get_cache().ensure_cached(info.announcement_id, info.pdf_url)
    return _get_cache().read_lines(
        info.announcement_id, offset, limit
    )
