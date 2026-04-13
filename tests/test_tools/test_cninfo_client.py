"""CninfoClient 单元测试。

覆盖范围：搜索基本流程、分页、关键词过滤、PDF 下载、异常。
外部依赖：httpx 请求全部 mock。
"""

import pytest

class TestCninfoClientSearch:
    """CninfoClient.search 测试。"""

    @pytest.mark.asyncio
    async def test_search_basic(self):
        """Given: mock 响应含 2 条公告，无分页
        When: 调用 search("600519")
        Then: 返回 2 条 AnnouncementInfo"""

    @pytest.mark.asyncio
    async def test_search_with_page(self):
        """Given: mock 响应 totalAnnouncement=50
        When: 调用 search(page=2)
        Then: 返回第 2 页数据 + total=50"""

    @pytest.mark.asyncio
    async def test_search_empty_result(self):
        """Given: totalAnnouncement=0
        When: 调用 search
        Then: 返回空列表"""

    @pytest.mark.asyncio
    async def test_search_default_date_range(self):
        """Given: 未传 start_date/end_date
        When: 调用 search
        Then: 默认近一年范围"""

class TestCninfoClientDownload:
    """CninfoClient.download_pdf 测试。"""

    @pytest.mark.asyncio
    async def test_download_success(self):
        """Given: mock 返回 200 + PDF bytes
        When: 调用 download_pdf
        Then: 返回对应 bytes"""

    @pytest.mark.asyncio
    async def test_download_http_error(self):
        """Given: mock 返回 404
        When: 调用 download_pdf
        Then: 抛出 HTTPStatusError"""

    @pytest.mark.asyncio
    async def test_download_timeout(self):
        """Given: mock 超时
        When: 调用 download_pdf
        Then: 抛出 TimeoutException"""
