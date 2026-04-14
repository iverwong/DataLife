"""公告查询工具函数测试。

覆盖范围：三个 @tool 函数的编排逻辑。
外部依赖全部 mock：CninfoClient、AnnouncementCache。
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tools.services.types import (
    AnnouncementInfo,
    GrepMatch,
)

# ── Fixtures ─────────────────────────────────────────────

SAMPLE_INFO = AnnouncementInfo(
    announcement_id="ann_001",
    stock_code="600519",
    stock_name="贵州茅台",
    title="2025年年度报告",
    published_date=date(2026, 3, 28),
    pdf_url="https://static.cninfo.com.cn/finalpage/xxx.PDF",
    size_kb=2048,
)

class TestSearchAnnouncements:
    """search_announcements 工具测试。

    覆盖范围：正常搜索、空结果、日期范围解析。
    外部依赖 mock：CninfoClient.search。
    """

    @pytest.mark.asyncio
    async def test_search_returns_formatted_results(self):
        """Given: CninfoClient.search 返回 1 条公告
        When: 调用 search_announcements("年报", "600519")
        Then: 返回包含公告 id 和标题的格式化字符串；
              _registry 包含该公告"""
        with patch(
            "core.tools.announcement._client"
        ) as mock_client:
            mock_client.search = AsyncMock(
                return_value=([SAMPLE_INFO], 1)
            )
            from core.tools.announcement import (
                _registry,
                search_announcements,
            )

            result = await search_announcements.ainvoke(
                {"keyword": "年报", "stock_code": "600519"}
            )
            assert "ann_001" in result
            assert "2025年年度报告" in result
            assert "ann_001" in _registry

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        """Given: CninfoClient.search 返回空列表
        When: 调用 search_announcements
        Then: 返回"未找到"提示"""
        with patch(
            "core.tools.announcement._client"
        ) as mock_client:
            mock_client.search = AsyncMock(return_value=([], 0))
            from core.tools.announcement import (
                search_announcements,
            )

            result = await search_announcements.ainvoke(
                {"keyword": "不存在", "stock_code": "000000"}
            )
            assert "未找到" in result

    @pytest.mark.asyncio
    async def test_search_with_date_range(self):
        """Given: date_range = "2026-01-01~2026-03-31"
        When: 调用 search_announcements
        Then: CninfoClient.search 收到正确的 start/end date"""
        with patch(
            "core.tools.announcement._client"
        ) as mock_client:
            mock_client.search = AsyncMock(return_value=([], 0))
            from core.tools.announcement import (
                search_announcements,
            )

            await search_announcements.ainvoke(
                {
                    "keyword": "年报",
                    "stock_code": "600519",
                    "date_range": "2026-01-01~2026-03-31",
                }
            )
            mock_client.search.assert_called_once_with(
                "600519",
                "年报",
                "",
                date(2026, 1, 1),
                date(2026, 3, 31),
                1,
            )

class TestGrepAnnouncement:
    """grep_announcement 工具测试。

    覆盖范围：正常 grep、未注册公告、无匹配。
    外部依赖 mock：AnnouncementCache。
    """

    @pytest.mark.asyncio
    async def test_grep_returns_matches(self):
        """Given: 公告已注册且缓存，关键词有 2 处匹配
        When: 调用 grep_announcement
        Then: 返回包含行号和上下文的格式化结果"""
        matches = [
            GrepMatch(
                line_number=10,
                content="营业收入 1850 亿元",
                context_before=["财务数据摘要"],
                context_after=["同比增长 15%"],
            ),
            GrepMatch(
                line_number=42,
                content="营业收入构成分析",
                context_before=["第三章"],
                context_after=["其中白酒业务"],
            ),
        ]
        with (
            patch(
                "core.tools.announcement._registry",
                {"ann_001": SAMPLE_INFO},
            ),
            patch(
                "core.tools.announcement._cache"
            ) as mock_cache,
        ):
            mock_cache.ensure_cached = AsyncMock()
            mock_cache.grep = MagicMock(return_value=matches)
            mock_cache.get_total_lines = MagicMock(
                return_value=500
            )
            from core.tools.announcement import (
                grep_announcement,
            )

            result = await grep_announcement.ainvoke(
                {
                    "announcement_id": "ann_001",
                    "pattern": "营业收入",
                }
            )
            assert "10" in result
            assert "42" in result

    @pytest.mark.asyncio
    async def test_grep_not_registered(self):
        """Given: announcement_id 不在 _registry
        When: 调用 grep_announcement
        Then: 返回包含"搜索"建议的错误提示"""
        with patch(
            "core.tools.announcement._registry", {}
        ):
            from core.tools.announcement import (
                grep_announcement,
            )

            result = await grep_announcement.ainvoke(
                {
                    "announcement_id": "unknown",
                    "pattern": "test",
                }
            )
            assert "search_announcements" in result or "搜索" in result

class TestReadAnnouncement:
    """read_announcement 工具测试。

    覆盖范围：正常读取、未注册。
    外部依赖 mock：AnnouncementCache。
    """

    @pytest.mark.asyncio
    async def test_read_returns_content(self):
        """Given: 公告已注册且缓存
        When: 调用 read_announcement(1, 10)
        Then: 返回指定行范围文本"""
        with (
            patch(
                "core.tools.announcement._registry",
                {"ann_001": SAMPLE_INFO},
            ),
            patch(
                "core.tools.announcement._cache"
            ) as mock_cache,
        ):
            mock_cache.ensure_cached = AsyncMock()
            mock_cache.read_lines = MagicMock(
                return_value="L1: 第一行\nL2: 第二行"
            )
            from core.tools.announcement import (
                read_announcement,
            )

            result = await read_announcement.ainvoke(
                {
                    "announcement_id": "ann_001",
                    "offset": 1,
                    "limit": 10,
                }
            )
            assert "第一行" in result

    @pytest.mark.asyncio
    async def test_read_not_registered(self):
        """Given: announcement_id 不在 _registry
        When: 调用 read_announcement
        Then: 返回错误提示"""
        with patch(
            "core.tools.announcement._registry", {}
        ):
            from core.tools.announcement import (
                read_announcement,
            )

            result = await read_announcement.ainvoke(
                {
                    "announcement_id": "unknown",
                    "offset": 1,
                    "limit": 10,
                }
            )
            assert "搜索" in result or "未找到" in result
