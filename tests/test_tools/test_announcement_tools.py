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
    SearchInput,
)


class TestFormatGrepResults:
    """_format_grep_results 输出格式测试。

    覆盖范围：总命中数提示、截断提示、行号标注、区间合并展示。
    外部依赖：无（纯格式化逻辑）。
    """

    def _make_match(
        self,
        line_number: int,
        content: str,
        ctx_before: list[str],
        ctx_after: list[str],
    ) -> GrepMatch:
        return GrepMatch(
            line_number=line_number,
            content=content,
            context_before=ctx_before,
            context_after=ctx_after,
        )

    def test_total_match_count_shown(self) -> None:
        """Given: 全文共 5 条命中，head_limit=3，传入前 3 条
        When: 调用 _format_grep_results
        Then: 输出包含「共 5 条匹配」以及截断提示「显示前 3 条"""
        from core.tools.announcement import _format_grep_results

        all_lines = [f"line {i}" for i in range(1, 21)]
        matches = [
            self._make_match(
                3, "line 3", ["line 1", "line 2"], ["line 4", "line 5"]
            ),
            self._make_match(
                10, "line 10", ["line 8", "line 9"], ["line 11", "line 12"]
            ),
            self._make_match(
                18, "line 18", ["line 16", "line 17"], ["line 19", "line 20"]
            ),
        ]
        result = _format_grep_results(
            matches=matches,
            total_lines=20,
            total_matches=5,
            before=2,
            after=2,
            all_lines=all_lines,
        )
        assert "共 5 条匹配" in result
        assert "显示前 3 条" in result

    def test_no_truncation_message_when_all_shown(self) -> None:
        """Given: 全文 2 条命中，head_limit=30，传入全部 2 条
        When: 调用 _format_grep_results
        Then: 包含「共 2 条匹配」，不含截断提示"""
        from core.tools.announcement import _format_grep_results

        all_lines = [f"line {i}" for i in range(1, 11)]
        matches = [
            self._make_match(2, "line 2", ["line 1"], ["line 3"]),
            self._make_match(8, "line 8", ["line 7"], ["line 9"]),
        ]
        result = _format_grep_results(
            matches=matches,
            total_lines=10,
            total_matches=2,
            before=1,
            after=1,
            all_lines=all_lines,
        )
        assert "共 2 条匹配" in result
        assert "显示前" not in result

    def test_context_lines_have_line_numbers(self) -> None:
        """Given: 1 条命中，前后各 1 行上下文
        When: 调用 _format_grep_results
        Then: 命中行和上下文行都以 L{n}: 格式标注行号"""
        from core.tools.announcement import _format_grep_results

        all_lines = ["ctx before", "matched line", "ctx after"]
        matches = [
            self._make_match(2, "matched line", ["ctx before"], ["ctx after"]),
        ]
        result = _format_grep_results(
            matches=matches,
            total_lines=3,
            total_matches=1,
            before=1,
            after=1,
            all_lines=all_lines,
        )
        assert "L1:" in result
        assert "L2:" in result
        assert "L3:" in result

    def test_overlapping_contexts_merged(self) -> None:
        """Given: 两条命中行号相邻（L3 和 L5），context_lines=3 时上下文重叠
        When: 调用 _format_grep_results
        Then: 输出为一个连续区间，不出现重复行，且两条命中都被标注"""
        from core.tools.announcement import _format_grep_results

        all_lines = [f"line {i}" for i in range(1, 11)]
        matches = [
            self._make_match(
                3, "line 3", ["line 1", "line 2"], ["line 4", "line 5"]
            ),
            self._make_match(
                5, "line 5", ["line 3", "line 4"], ["line 6", "line 7"]
            ),
        ]
        result = _format_grep_results(
            matches=matches,
            total_lines=10,
            total_matches=2,
            before=2,
            after=2,
            all_lines=all_lines,
        )
        # 合并后只有一个区间分隔符
        assert result.count("---") <= 2  # 最多 1 个区间块（2 个 ---）
        # 每行只出现一次
        assert result.count("L3:") == 1
        assert result.count("L4:") == 1
        assert result.count("L5:") == 1

    def test_empty_matches(self) -> None:
        """Given: 无命中
        When: 调用 _format_grep_results
        Then: 返回「未找到匹配内容」"""
        from core.tools.announcement import _format_grep_results

        result = _format_grep_results(
            matches=[],
            total_lines=100,
            total_matches=0,
            before=2,
            after=2,
            all_lines=[],
        )
        assert result == "未找到匹配内容"


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
        """Given: start_date="2026-01-01", end_date="2026-03-31"
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
                    "start_date": "2026-01-01",
                    "end_date": "2026-03-31",
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
            mock_cache.get_all_lines = MagicMock(
                return_value=(
                    "line0\n" * 9
                    + "营业收入 1850 亿元\n"
                    + "line11\n" * 31
                    + "营业收入构成分析\n"
                    + "line43\n" * 458
                ).splitlines()
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


class TestSearchInputSchema:
    """SearchInput schema 测试。

    覆盖：keyword / stock_code 已改为可选（默认空字符串）。
    """

    def test_keyword_optional_defaults_to_empty(self) -> None:
        """Given: 不传 keyword
        When: 构造 SearchInput(stock_code="600519")
        Then: keyword == """""
        inp = SearchInput(stock_code="600519")
        assert inp.keyword == ""

    def test_stock_code_optional_defaults_to_empty(self) -> None:
        """Given: 不传 stock_code
        When: 构造 SearchInput(keyword="年报")
        Then: stock_code == """""
        inp = SearchInput(keyword="年报")
        assert inp.stock_code == ""

    def test_both_optional_construct_empty(self) -> None:
        """Given: keyword 和 stock_code 均不传
        When: 构造 SearchInput()
        Then: 两者均为空字符串，不抛验证异常"""
        inp = SearchInput()
        assert inp.keyword == ""
        assert inp.stock_code == ""
