"""CninfoClient 单元测试。

覆盖范围：搜索基本流程、分页、关键词过滤、PDF 下载、异常。
外部依赖：httpx 请求全部 mock。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.data.api_models import AnnouncementItem
from core.tools.services.cninfo_client import CninfoClient
from core.tools.services.types import AnnouncementInfo


def _make_item(
    announcement_id: str,
    sec_code: str,
    sec_name: str,
    title: str,
    timestamp_ms: int,
    adjunct_url: str = "/finalpage/2026/test.pdf",
    adjunct_size: int = 2048,
) -> AnnouncementItem:
    """Helper: 构造 AnnouncementItem。"""
    return AnnouncementItem(
        announcementId=announcement_id,
        secCode=sec_code,
        secName=sec_name,
        orgId="org001",
        announcementTitle=title,
        announcementTime=timestamp_ms,
        adjunctUrl=adjunct_url,
        adjunctSize=adjunct_size,
    )


class TestCninfoClientSearch:
    """CninfoClient.search 测试。"""

    @pytest.mark.asyncio
    async def test_search_basic(self):
        """Given: mock 响应含 2 条公告，无分页
        When: 调用 search("600519")
        Then: 返回 2 条 AnnouncementInfo"""
        now_ms = int(datetime.now().timestamp() * 1000)
        items = [
            _make_item(
                "ann_001", "600519", "贵州茅台",
                "2025年年度报告", now_ms,
            ),
            _make_item(
                "ann_002", "600519", "贵州茅台",
                "2026年第一季度报告", now_ms,
            ),
        ]

        with (
            patch.object(
                CninfoClient, "_get_stock_org_mapping",
                new_callable=AsyncMock,
                return_value={"600519": "org001"},
            ),
            patch.object(
                CninfoClient, "_fetch_page",
                new_callable=AsyncMock,
                return_value=(items, 2),
            ) as mock_fetch,
        ):
            client = CninfoClient()
            result, total = await client.search("600519")

        assert total == 2
        assert len(result) == 2
        assert all(isinstance(r, AnnouncementInfo) for r in result)
        assert result[0].announcement_id == "ann_001"
        assert result[1].announcement_id == "ann_002"
        assert result[0].stock_code == "600519"
        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_page(self):
        """Given: mock 响应 totalAnnouncement=50
        When: 调用 search(page=2)
        Then: 返回第 2 页数据 + total=50"""
        now_ms = int(datetime.now().timestamp() * 1000)
        items = [
            _make_item(
                f"ann_{i:03d}", "600519", "贵州茅台",
                f"公告标题{i}", now_ms - i * 86400000,
            )
            for i in range(1, 31)
        ]

        with (
            patch.object(
                CninfoClient, "_get_stock_org_mapping",
                new_callable=AsyncMock,
                return_value={"600519": "org001"},
            ),
            patch.object(
                CninfoClient, "_fetch_page",
                new_callable=AsyncMock,
                return_value=(items, 50),
            ) as mock_fetch,
        ):
            client = CninfoClient()
            result, got_total = await client.search("600519", page=2)

        assert got_total == 50
        assert len(result) == 30
        # 验证 page=2 传给了 _fetch_page
        # signature: _fetch_page(stock_item, keyword, category, start_date, end_date, page=1)
        # page 是第 6 个位置参数
        call_args = mock_fetch.call_args
        assert call_args[0][5] == 2

    @pytest.mark.asyncio
    async def test_search_empty_result(self):
        """Given: totalAnnouncement=0
        When: 调用 search
        Then: 返回空列表"""
        with (
            patch.object(
                CninfoClient, "_get_stock_org_mapping",
                new_callable=AsyncMock,
                return_value={"600519": "org001"},
            ),
            patch.object(
                CninfoClient, "_fetch_page",
                new_callable=AsyncMock,
                return_value=([], 0),
            ),
        ):
            client = CninfoClient()
            result, total = await client.search("600519")

        assert result == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_search_default_date_range(self):
        """Given: 未传 start_date/end_date
        When: 调用 search
        Then: 默认近一年范围"""
        today = date.today()
        expected_start = today - timedelta(days=365)
        expected_end = today + timedelta(days=1)

        with (
            patch.object(
                CninfoClient, "_get_stock_org_mapping",
                new_callable=AsyncMock,
                return_value={"600519": "org001"},
            ),
            patch.object(
                CninfoClient, "_fetch_page",
                new_callable=AsyncMock,
                return_value=([], 0),
            ) as mock_fetch,
        ):
            client = CninfoClient()
            _, _ = await client.search("600519")

        # signature: _fetch_page(stock_item, keyword, category, start_date, end_date, page=1)
        # start_date 是第 4 个位置参数 (index 3), end_date 是第 5 个 (index 4)
        call_args = mock_fetch.call_args
        assert call_args[0][3] == expected_start
        assert call_args[0][4] == expected_end


class TestCninfoClientDownload:
    """CninfoClient.download_pdf 测试。"""

    @pytest.mark.asyncio
    async def test_download_success(self):
        """Given: mock 返回 200 + PDF bytes
        When: 调用 download_pdf
        Then: 返回对应 bytes"""
        pdf_bytes = b"%PDF-1.4 fake content"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = pdf_bytes
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(
            CninfoClient, "_get_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            client = CninfoClient()
            result = await client.download_pdf(
                "https://static.cninfo.com.cn/finalpage/2026/test.pdf"
            )

        assert result == pdf_bytes

    @pytest.mark.asyncio
    async def test_download_http_error(self):
        """Given: mock 返回 404
        When: 调用 download_pdf
        Then: 抛出 HTTPStatusError"""
        mock_response = MagicMock()
        mock_response.status_code = 404

        def raise_for_status():
            raise httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )

        mock_response.raise_for_status = raise_for_status

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(
            CninfoClient, "_get_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            client = CninfoClient()
            with pytest.raises(httpx.HTTPStatusError):
                _ = await client.download_pdf(
                    "https://static.cninfo.com.cn/nonexistent.pdf"
                )

    @pytest.mark.asyncio
    async def test_download_timeout(self):
        """Given: mock 超时
        When: 调用 download_pdf
        Then: 抛出 TimeoutException"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.TimeoutException("connection timeout")
        )

        with patch.object(
            CninfoClient, "_get_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            client = CninfoClient()
            with pytest.raises(httpx.TimeoutException):
                _ = await client.download_pdf(
                    "https://static.cninfo.com.cn/finalpage/slow.pdf"
                )
