import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.business_data_handler import (
    _should_update_half_year,
    process_business_data_for_stock_list,
)
from core.notion import StockPool
from tests.resource.manager import resource_manager


def _patch_datetime(now_value):
    """mock datetime.now() 同时保留 strptime 和构造器的真实行为"""
    p = patch("core.business_data_handler.datetime", wraps=datetime)
    mock_dt = p.start()
    mock_dt.now.return_value = now_value
    return p, mock_dt


class TestShouldUpdateHalfYear:
    def test_none_returns_true(self):
        """从未更新过，应当返回 True"""
        assert _should_update_half_year(None) is True

    def test_empty_string_returns_true(self):
        """空字符串视同未更新"""
        assert _should_update_half_year("") is True

    def test_q2_before_next_year(self):
        """上次更新为 6/30（Q2），在下一年1月1日00:00:00之前不需要更新"""
        p, _ = _patch_datetime(datetime(2025, 12, 31, 23, 59, 59))
        try:
            assert _should_update_half_year("2025-06-30") is False
        finally:
            p.stop()

    def test_q2_after_next_year(self):
        """上次更新为 6/30（Q2），到了下一年1月1日00:00:00应当更新"""
        p, _ = _patch_datetime(datetime(2026, 1, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-06-30") is True
        finally:
            p.stop()

    def test_q2_exactly_next_year_boundary(self):
        """上次更新为 6/30（Q2），恰好在1月1日00:00:00边界上应当更新（>=）"""
        p, _ = _patch_datetime(datetime(2026, 1, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-06-30") is True
        finally:
            p.stop()

    def test_q4_before_next_july(self):
        """上次更新为 12/31（Q4），在下一年7月1日00:00:00之前不需要更新"""
        p, _ = _patch_datetime(datetime(2026, 6, 30, 23, 59, 59))
        try:
            assert _should_update_half_year("2025-12-31") is False
        finally:
            p.stop()

    def test_q4_after_next_july(self):
        """上次更新为 12/31（Q4），到了下一年7月1日00:00:00应当更新"""
        p, _ = _patch_datetime(datetime(2026, 7, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-12-31") is True
        finally:
            p.stop()

    def test_q4_exactly_july_boundary(self):
        """上次更新为 12/31（Q4），恰好在7月1日00:00:00边界上应当更新（>=）"""
        p, _ = _patch_datetime(datetime(2026, 7, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-12-31") is True
        finally:
            p.stop()

    def test_non_quarter_end_returns_false(self):
        """非季度末日期（如 3/15）应返回 False 并记录错误"""
        assert _should_update_half_year("2025-03-15") is False

    def test_iso_datetime_string_extracts_date_part(self):
        """带时间戳的 ISO 字符串，只取前10字符作为日期"""
        p, _ = _patch_datetime(datetime(2026, 1, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-06-30T12:00:00.000+08:00") is True
        finally:
            p.stop()


@pytest_asyncio.fixture(scope="function")
async def memory_db():
    """创建内存数据库用于测试"""
    # 创建内存数据库连接
    conn = await aiosqlite.connect(":memory:")

    # 创建所需的表结构
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS update_records (
            stock TEXT NOT NULL,
            key TEXT NOT NULL,
            update_time TEXT,
            PRIMARY KEY (stock, key)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hash (
            hash TEXT PRIMARY KEY,
            create_at TEXT NOT NULL
        )
    """)
    await conn.commit()

    # 注入到 db 模块中
    import core.db

    original_db = core.db.db
    core.db.db = conn

    yield conn

    # 恢复原始连接
    core.db.db = original_db
    await conn.close()


@pytest.mark.asyncio
class TestProcessBusinessData:
    """测试 process_business_data_for_stock_list 完整流程"""

    async def test_process_new_stock_creates_page(self, memory_db):
        """测试处理新股票（无更新记录）时创建页面"""
        # 准备测试数据 - 使用静态资源
        resource = resource_manager.load("ygdq_300274_business")
        business_df = resource.get_data()

        # 创建股票池对象
        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        # 只 Mock 外部依赖（数据获取和 Notion API），数据库使用真实内存数据库
        with (
            patch("core.business_data_handler.get_business") as mock_get_business,
            patch(
                "core.business_data_handler.create_dataflow_page"
            ) as mock_create_page,
        ):
            # 设置 mock 返回值
            mock_get_business.return_value = MagicMock(
                report_date=date(2025, 6, 30),
                industry_df=business_df[business_df["分类类型"].isna()].head(5),
                product_df=business_df[business_df["分类类型"] == "按产品分类"].head(5),
                region_df=business_df[business_df["分类类型"] == "按地区分类"].head(5),
            )
            mock_create_page.return_value = None

            # 执行测试
            await process_business_data_for_stock_list(stock_list)

            # 验证外部调用
            mock_create_page.assert_called_once()

            # 验证数据库状态
            cursor = await memory_db.execute(
                "SELECT update_time FROM update_records WHERE stock = ? AND key = ?",
                ("300274", "business"),
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == "2025-06-30"

            # 验证 hash 已保存
            cursor = await memory_db.execute("SELECT COUNT(*) FROM hash")
            count = await cursor.fetchone()
            assert count[0] > 0

    async def test_process_existing_stock_skips_update(self, memory_db):
        """测试已更新的股票跳过处理"""
        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        # 在数据库中插入已更新记录
        await memory_db.execute(
            "INSERT INTO update_records (stock, key, update_time) VALUES (?, ?, ?)",
            ("300274", "business", "2024-12-31"),
        )
        await memory_db.commit()

        # Mock 当前时间为 2025-06-15（在更新周期内）
        with (
            patch(
                "core.business_data_handler._should_update_half_year"
            ) as mock_should_update,
            patch("core.business_data_handler.get_business") as mock_get_business,
        ):
            mock_should_update.return_value = False  # 不需要更新

            # 执行测试
            await process_business_data_for_stock_list(stock_list)

            # 验证：不应获取业务数据
            mock_get_business.assert_not_called()

            # 验证数据库状态未改变
            cursor = await memory_db.execute(
                "SELECT update_time FROM update_records WHERE stock = ? AND key = ?",
                ("300274", "business"),
            )
            result = await cursor.fetchone()
            assert result[0] == "2024-12-31"

    async def test_duplicate_hash_skips_creation(self, memory_db):
        """测试重复 hash 跳过页面创建"""
        resource = resource_manager.load("ygdq_300274_business")
        business_df = resource.get_data()

        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        # 先执行一次完整流程，将 hash 保存到数据库
        with (
            patch("core.business_data_handler.get_business") as mock_get_business,
            patch(
                "core.business_data_handler.create_dataflow_page"
            ) as mock_create_page,
        ):
            mock_get_business.return_value = MagicMock(
                report_date=date(2025, 6, 30),
                industry_df=business_df[business_df["分类类型"].isna()].head(5),
                product_df=business_df[business_df["分类类型"] == "按产品分类"].head(5),
                region_df=business_df[business_df["分类类型"] == "按地区分类"].head(5),
            )

            await process_business_data_for_stock_list(stock_list)
            first_call_count = mock_create_page.call_count
            assert first_call_count == 1

        # 第二次执行，应该因为 hash 重复而跳过
        with (
            patch("core.business_data_handler.get_business") as mock_get_business2,
            patch(
                "core.business_data_handler.create_dataflow_page"
            ) as mock_create_page2,
        ):
            mock_get_business2.return_value = MagicMock(
                report_date=date(2025, 6, 30),
                industry_df=business_df[business_df["分类类型"].isna()].head(5),
                product_df=business_df[business_df["分类类型"] == "按产品分类"].head(5),
                region_df=business_df[business_df["分类类型"] == "按地区分类"].head(5),
            )

            await process_business_data_for_stock_list(stock_list)

            # 验证：不应创建页面
            mock_create_page2.assert_not_called()

    async def test_process_multiple_stocks(self, memory_db):
        """测试处理多只股票"""
        stock_list = [
            StockPool(id="test-id-1", code="300274"),
            StockPool(id="test-id-2", code="300750"),
        ]

        with (
            patch("core.business_data_handler.get_business") as mock_get_business,
            patch(
                "core.business_data_handler.create_dataflow_page"
            ) as mock_create_page,
        ):
            # 模拟返回不同股票的数据
            async def mock_business_side_effect(stock_code):
                return MagicMock(
                    report_date=date(2025, 6, 30),
                    industry_df=MagicMock(),
                    product_df=MagicMock(),
                    region_df=MagicMock(),
                )

            mock_get_business.side_effect = mock_business_side_effect

            await process_business_data_for_stock_list(stock_list)

            # 验证：应为每只股票创建页面
            assert mock_create_page.call_count == 2
            mock_get_business.assert_any_call("300274")
            mock_get_business.assert_any_call("300750")

            # 验证数据库中两只股票的记录都已创建
            cursor = await memory_db.execute(
                "SELECT stock, update_time FROM update_records WHERE key = ? ORDER BY stock",
                ("business",),
            )
            results = await cursor.fetchall()
            assert len(results) == 2
            assert results[0][0] == "300274"
            assert results[0][1] == "2025-06-30"
            assert results[1][0] == "300750"
            assert results[1][1] == "2025-06-30"
