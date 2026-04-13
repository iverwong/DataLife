"""巨潮资讯网 API 异步客户端。

职责：搜索公告列表、下载公告 PDF。
重写 core/data/announcement.py，去除 Notion 绑定，纯数据获取。
"""

from __future__ import annotations

from datetime import date

import httpx

from core.data.api_models import AnnouncementItem
from core.tools.services.types import AnnouncementInfo

CNINFO_BASE_URL = "https://static.cninfo.com.cn/"
CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"

class CninfoClient:
    """巨潮资讯网 API 异步客户端。

    支持注入 httpx.AsyncClient 以复用连接；
    未注入时每次调用创建临时 client。
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        raise NotImplementedError

    async def search(
        self,
        stock_code: str,
        keyword: str = "",
        category: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
    ) -> tuple[list[AnnouncementInfo], int]:
        """搜索公告列表（单页，每页 30 条）。

        Args:
            stock_code: 股票代码（如 "600519"）。
            keyword: 搜索关键词（可选）。
            category: 巨潮 API category 代码（已由 tool 层映射）。
            start_date: 查询起始日期（默认近一年）。
            end_date: 查询结束日期（默认明天）。
            page: 页码（从 1 开始，默认 1）。

        Returns:
            (当页公告列表, 总条数)。
        """
        raise NotImplementedError

    async def download_pdf(self, pdf_url: str) -> bytes:
        """下载公告 PDF 文件。

        Args:
            pdf_url: PDF 完整下载链接。

        Returns:
            PDF 文件二进制内容。

        Raises:
            httpx.HTTPStatusError: 下载失败。
        """
        raise NotImplementedError

    async def _get_stock_org_mapping(self) -> dict[str, str]:
        """获取股票代码到机构 ID 的映射。

        Returns:
            {stock_code: org_id} 映射字典。
        """
        raise NotImplementedError

    async def _fetch_page(
        self,
        stock_item: str,
        keyword: str,
        category: str,
        start_date: date,
        end_date: date,
        page: int = 1,
    ) -> tuple[list[AnnouncementItem], int]:
        """获取单页公告数据。

        Args:
            stock_item: 格式化的股票查询字符串（code,orgId）。
            keyword: 搜索关键词。
            category: 巨潮 API category 代码（已映射）。
            start_date: 起始日期。
            end_date: 结束日期。
            page: 页码（从 1 开始）。

        Returns:
            (当页 AnnouncementItem 列表, 总条数)。
        """
        raise NotImplementedError
