"""巨潮资讯网公告数据采集模块。

从巨潮资讯网 API 查询上市公司公告，支持分页获取和关键词过滤。
"""

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache

import httpx
import logfire

from .api_models import AnnouncementItem, AnnouncementsResponse, StockListResponse


@dataclass(frozen=True)
class Announcement:
    """巨潮资讯网公告信息。

    Attributes:
        id: 巨潮资讯网公告的唯一标识符。
        stock: 公告所属的股票代码。
        title: 公告标题。
        size: 公告文件大小（KB）。
        url: 公告文件的下载链接。
        published_date: 公告发布日期。
    """

    id: str
    stock: str
    title: str
    size: int
    url: str
    published_date: datetime


@dataclass(frozen=True)
class AnnouncementWithContent(Announcement):
    """带有文件二进制内容的公告。

    Attributes:
        content: PDF 文件的二进制内容，默认为空字节。
    """

    content: bytes = b""


CNINFO_BASE_URL = "https://static.cninfo.com.cn/"
FILTERED_KEYWORDS = ["摘要", "英文", "图文版"]

# 懒加载：httpx.AsyncClient 初始为 None，首次调用时创建
_httpx_client: httpx.AsyncClient | None = None


def get_httpx_client() -> httpx.AsyncClient:
    """获取 httpx.AsyncClient 实例（懒加载）。

    首次调用时创建客户端并缓存，后续调用直接返回。
    与 Notion 客户端分离，无速率限制，适合巨潮 API 调用。
    """
    global _httpx_client
    if _httpx_client is None:
        _httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
    return _httpx_client


async def close_httpx_client() -> None:
    """关闭 httpx.AsyncClient 客户端。

    提供幂等性保护：若客户端已关闭或从未创建，则跳过关闭操作。
    """
    global _httpx_client

    if _httpx_client is None:
        logfire.debug("httpx.AsyncClient 从未创建，跳过关闭")
        return

    if _httpx_client.is_closed:
        logfire.debug("httpx.AsyncClient 已关闭，跳过")
        return

    try:
        await _httpx_client.aclose()
        logfire.debug("httpx.AsyncClient 已关闭")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logfire.debug("事件循环已关闭，跳过 httpx 客户端关闭")
        else:
            raise
    finally:
        _httpx_client = None


def _convert_item_to_announcement(item: AnnouncementItem) -> Announcement:
    """将 API 响应中的 AnnouncementItem 转换为 Announcement 数据类"""
    return Announcement(
        id=item.announcementId,
        stock=item.secCode,
        title=f"{item.secName}({item.secCode})-{item.announcementTitle}",
        size=item.adjunctSize,
        url=f"{CNINFO_BASE_URL}{item.adjunctUrl}",
        published_date=datetime.fromtimestamp(item.announcementTime / 1000),
    )


async def get_announcements(
    stock_list: list[str],
    start_date: date,
    end_date: date,
) -> list[Announcement]:
    """获取指定股票列表在给定日期范围内的公告信息。

    从巨潮资讯网 API 分页查询公告，并过滤掉摘要、英文版和图文版等非主体公告。

    Args:
        stock_list: 股票代码列表。
        start_date: 查询起始日期。
        end_date: 查询结束日期。

    Returns:
        过滤后的公告信息列表。

    Raises:
        httpx.HTTPStatusError: API 请求返回非 2xx 状态码。
    """

    if len(stock_list) == 0:
        logfire.warn("股票列表为空，跳过获取公告信息")
        return []

    logfire.info(
        "开始获取公告，股票: {stock_list}，范围: {start} ~ {end}",
        stock_list=stock_list,
        start=start_date,
        end=end_date,
    )

    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

    stock_item = ";".join(
        [f"{stock},{(await _get_stock_json())[stock]}" for stock in stock_list]
    )
    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_item,
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start_date}~{end_date}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }

    client = get_httpx_client()
    res = await client.post(url, params=payload)
    try:
        _ = res.raise_for_status()
    except httpx.HTTPStatusError:
        logfire.exception("获取公告请求失败")
        return []
    first_page = AnnouncementsResponse.model_validate(res.json())

    if first_page.totalAnnouncement == 0:
        logfire.info("未获取到公告数据")
        return []

    # 处理 announcements 为 None 的情况
    announcements: list[AnnouncementItem] = list(first_page.announcements or [])
    # 使用接口返回的totalpages参数获取**剩余**页数
    page_count = first_page.totalpages

    logfire.debug(
        "首页返回 {count} 条，总页数 {page_count}",
        count=len(announcements),
        page_count=page_count,
    )
    for i in range(page_count):
        payload["pageNum"] = str(i + 2)
        res = await client.post(url, params=payload)
        page = AnnouncementsResponse.model_validate(res.json())
        announcements.extend(page.announcements or [])

    # 将report中的摘要、英文版、图文版之类的筛选掉
    before_filter_count = len(announcements)
    filtered = [
        item
        for item in announcements
        if not any(kw in item.announcementTitle for kw in FILTERED_KEYWORDS)
    ]

    result = [_convert_item_to_announcement(item) for item in filtered]
    logfire.info(
        "公告获取完成，原始 {before} 条，过滤后 {after} 条",
        before=before_filter_count,
        after=len(result),
    )
    return result


@lru_cache()
async def _get_stock_json(symbol: str = "沪深京") -> dict[str, str]:
    """获取巨潮资讯网股票代码到机构 ID 的映射。

    使用 lru_cache 缓存结果，避免重复请求。

    Args:
        symbol: 股票市场类型，目前仅支持"沪深京"。

    Returns:
        以股票代码为键、机构 ID 为值的字典。

    Raises:
        ValueError: 当传入不支持的股票类型时抛出。
    """
    if symbol == "沪深京":
        url = "http://www.cninfo.com.cn/new/data/szse_stock.json"
    # 港股暂不考虑实现
    # elif symbol == "港股":
    #     url = "http://www.cninfo.com.cn/new/data/hke_stock.json"
    else:
        raise ValueError("不受支持的股票类型！")
    client = get_httpx_client()
    response = await client.get(url)
    stock_data = StockListResponse.model_validate(response.json())
    return {stock.code: stock.orgId for stock in stock_data.stockList}
