from datetime import date, datetime, timedelta

import httpx
import logfire

from core.tools.services.cninfo_api_models import (
    AnnouncementItem,
    AnnouncementsResponse,
    StockListResponse,
)
from core.tools.services.types import AnnouncementInfo

CNINFO_BASE_URL = "https://static.cninfo.com.cn/"
CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"

# 模块级缓存：股票代码 → 机构 ID 映射
_stock_org_cache: dict[str, str] | None = None


def _convert_item(item: AnnouncementItem) -> AnnouncementInfo:
    """将 API 原始条目转为 AnnouncementInfo。"""
    return AnnouncementInfo(
        announcement_id=item.announcementId,
        stock_code=item.secCode,
        stock_name=item.secName,
        title=f"{item.secName}({item.secCode})-{item.announcementTitle}",
        published_date=datetime.fromtimestamp(item.announcementTime / 1000).date(),
        pdf_url=f"{CNINFO_BASE_URL}{item.adjunctUrl}",
        size_kb=item.adjunctSize,
    )


class CninfoClient:
    _external_client: httpx.AsyncClient | None

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._external_client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(timeout=30.0)

    async def search(
        self,
        stock_code: str,
        keyword: str = "",
        category: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
    ) -> tuple[list[AnnouncementInfo], int]:
        # TODO 整体考虑下港股的情况（目前都是依靠A股构建的）
        if not stock_code:
            logfire.warn("股票代码为空，跳过搜索")
            return [], 0

        today = date.today()
        _start = start_date or (today - timedelta(days=365))
        _end = end_date or (today + timedelta(days=1))

        # TODO 这里的 org_mapping 考虑下缓存
        org_map = await self._get_stock_org_mapping()
        org_id = org_map.get(stock_code, "")
        stock_item = f"{stock_code},{org_id}"

        logfire.info(
            "搜索公告: stock={stock}, keyword={kw}, "
            + "category={cat}, range={s}~{e}, page={p}",
            stock=stock_code,
            kw=keyword,
            cat=category,
            s=_start,
            e=_end,
            p=page,
        )

        raw_items, total = await self._fetch_page(
            stock_item,
            keyword,
            category,
            _start,
            _end,
            page,
        )

        result = [_convert_item(item) for item in raw_items]
        logfire.info(
            "公告搜索完成: 当页 {count} 条，总 {total} 条",
            count=len(result),
            total=total,
        )
        return result, total

    async def download_pdf(self, pdf_url: str) -> bytes:
        client = await self._get_client()
        try:
            response = await client.get(pdf_url)
            _ = response.raise_for_status()
            return response.content
        finally:
            if self._external_client is None:
                await client.aclose()

    async def _get_stock_org_mapping(self) -> dict[str, str]:
        global _stock_org_cache
        if _stock_org_cache is not None:
            return _stock_org_cache

        client = await self._get_client()
        try:
            response = await client.get(CNINFO_STOCK_URL, timeout=30.0)
            stock_data = StockListResponse.model_validate(response.json())
            _stock_org_cache = {s.code: s.orgId for s in stock_data.stockList}
            return _stock_org_cache
        finally:
            if self._external_client is None:
                await client.aclose()

    async def _fetch_page(
        self,
        stock_item: str,
        keyword: str,
        category: str,
        start_date: date,
        end_date: date,
        page: int = 1,
    ) -> tuple[list[AnnouncementItem], int]:
        payload = {
            "pageNum": str(page),
            "pageSize": "30",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": stock_item,
            "searchkey": keyword,
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }

        client = await self._get_client()
        try:
            res = await client.post(CNINFO_QUERY_URL, params=payload)
            try:
                _ = res.raise_for_status()
            except httpx.HTTPStatusError:
                logfire.exception("获取公告请求失败")
                return [], 0

            resp = AnnouncementsResponse.model_validate(res.json())
            total = resp.totalAnnouncement
            items = list(resp.announcements or [])
            return items, total
        finally:
            if self._external_client is None:
                await client.aclose()
