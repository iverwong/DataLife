"""
公告数据处理模块测试

测试 announcements_data_handler 的完整流程
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.announcements_data_handler import (
    SPLIT_KEYWORDS,
    process_announcements_data_for_stock_list,
)
from core.notion import StockPool
from tests.resource.manager import ResourceType, resource_manager


@pytest_asyncio.fixture(scope="function")
async def memory_db():
    """创建内存数据库用于测试"""
    conn = await aiosqlite.connect(":memory:")

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
class TestProcessAnnouncementsData:
    """测试 process_announcements_data_for_stock_list 完整流程"""

    async def test_process_new_stock_with_announcements(self, memory_db):
        """测试处理新股票（无更新记录）时获取并处理公告"""
        # 加载静态资源
        resource = resource_manager.load("ygdq_300274_announcements")
        announcements = resource.get_data()

        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        # 只 Mock 外部依赖，数据库使用真实内存数据库
        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann,
            patch(
                "core.announcements_data_handler.upload_files_with_url"
            ) as mock_upload_url,
            patch(
                "core.announcements_data_handler.upload_files_with_local"
            ) as mock_upload_local,
            patch(
                "core.announcements_data_handler.create_dataflow_page"
            ) as mock_create_page,
            patch("core.announcements_data_handler.split_pdf") as mock_split_pdf,
        ):
            # 设置 mock
            mock_get_ann.return_value = announcements

            # 上传文件 mock
            mock_upload_url.return_value = [
                {"file_id": "external-file-123"} for _ in announcements
            ]
            mock_upload_local.return_value = []
            mock_split_pdf.return_value = []

            # 执行测试
            await process_announcements_data_for_stock_list(stock_list)

            # 验证调用
            mock_get_ann.assert_called_once()

            # 验证创建了页面
            assert mock_create_page.call_count == len(announcements)

            # 验证数据库状态
            cursor = await memory_db.execute(
                "SELECT update_time FROM update_records WHERE stock = ? AND key = ?",
                ("300274", "announcements"),
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] is not None

            # 验证 hash 已保存
            cursor = await memory_db.execute("SELECT COUNT(*) FROM hash")
            count = await cursor.fetchone()
            assert count[0] == len(announcements)

    async def test_process_with_existing_update_time(self, memory_db):
        """测试有更新记录的股票只获取增量公告"""
        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        last_update = date(2025, 1, 15)  # 使用固定日期避免测试时日期变化

        # 在数据库中插入更新记录
        await memory_db.execute(
            "INSERT INTO update_records (stock, key, update_time) VALUES (?, ?, ?)",
            ("300274", "announcements", last_update.isoformat()),
        )
        await memory_db.commit()

        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann,
            patch(
                "core.announcements_data_handler.upload_files_with_url"
            ) as mock_upload_url,
            patch(
                "core.announcements_data_handler.upload_files_with_local"
            ) as mock_upload_local,
            patch(
                "core.announcements_data_handler.create_dataflow_page"
            ) as mock_create_page,
            patch("core.announcements_data_handler.split_pdf") as mock_split_pdf,
        ):
            mock_get_ann.return_value = []
            mock_upload_url.return_value = []
            mock_upload_local.return_value = []
            mock_split_pdf.return_value = []

            await process_announcements_data_for_stock_list(stock_list)

            # 验证：会查询两次 - 1次初始化（空列表）+ 1次按时间分组查询
            # 因为新股票（无更新时间）会触发一次查询，但这里股票有更新时间
            assert mock_get_ann.call_count >= 1
            # 验证其中一次调用使用了 last_update 作为起始日期
            found_last_update_call = False
            for call in mock_get_ann.call_args_list:
                args = call[0]
                if len(args) >= 2:
                    # 第二个参数是 start_date，可能是 date 或 datetime
                    start_date = args[1]
                    # 将 datetime 转换为 date 进行比较
                    if hasattr(start_date, "date"):
                        start_date = start_date.date()
                    if start_date == last_update:
                        found_last_update_call = True
                        break
            assert found_last_update_call, (
                f"未找到使用 {last_update} 作为起始日期的调用，实际调用: {mock_get_ann.call_args_list}"
            )

    async def test_duplicate_announcements_filtered(self, memory_db):
        """测试重复公告被过滤"""
        resource = resource_manager.load("ygdq_300274_announcements")
        announcements = resource.get_data()

        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        # 第一次执行，将 hash 保存到数据库
        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann,
            patch(
                "core.announcements_data_handler.upload_files_with_url"
            ) as mock_upload_url,
            patch(
                "core.announcements_data_handler.upload_files_with_local"
            ) as mock_upload_local,
            patch(
                "core.announcements_data_handler.create_dataflow_page"
            ) as mock_create_page,
            patch("core.announcements_data_handler.split_pdf") as mock_split_pdf,
        ):
            mock_get_ann.return_value = announcements
            mock_upload_url.return_value = [
                {"file_id": "external-file-123"} for _ in announcements
            ]
            mock_upload_local.return_value = []
            mock_split_pdf.return_value = []

            await process_announcements_data_for_stock_list(stock_list)
            first_call_count = mock_create_page.call_count
            assert first_call_count == len(announcements)

        # 第二次执行，应该因为 hash 重复而跳过
        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann2,
            patch(
                "core.announcements_data_handler.upload_files_with_url"
            ) as mock_upload_url2,
            patch(
                "core.announcements_data_handler.upload_files_with_local"
            ) as mock_upload_local2,
            patch(
                "core.announcements_data_handler.create_dataflow_page"
            ) as mock_create_page2,
            patch("core.announcements_data_handler.split_pdf") as mock_split_pdf2,
        ):
            mock_get_ann2.return_value = announcements
            mock_upload_url2.return_value = []
            mock_upload_local2.return_value = []
            mock_split_pdf2.return_value = []

            await process_announcements_data_for_stock_list(stock_list)

            # 验证：不应创建任何页面（因为所有公告都被过滤掉了）
            mock_create_page2.assert_not_called()

    async def test_file_upload_strategy(self, memory_db):
        """测试文件上传策略：小文件用外链，大文件且含关键词才分割"""
        resource = resource_manager.load("ygdq_300274_announcements")
        announcements = resource.get_data()

        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann,
            patch(
                "core.announcements_data_handler.upload_files_with_url"
            ) as mock_upload_url,
            patch(
                "core.announcements_data_handler.upload_files_with_local"
            ) as mock_upload_local,
            patch("core.announcements_data_handler.create_dataflow_page"),
            patch("core.announcements_data_handler.split_pdf") as mock_split_pdf,
        ):
            mock_get_ann.return_value = announcements

            mock_upload_url.return_value = [
                {"file_id": f"url-file-{i}"} for i in range(len(announcements))
            ]
            mock_upload_local.return_value = []
            mock_split_pdf.return_value = []

            await process_announcements_data_for_stock_list(stock_list)

            # 验证外链上传被调用
            mock_upload_url.assert_called_once()

            # 验证 split_pdf 被调用（检查是否有大文件需要分割）
            mock_split_pdf.assert_called_once()

    async def test_process_multiple_stocks_grouped(self, memory_db):
        """测试多只股票按更新时间分组查询"""
        stock_list = [
            StockPool(id="test-id-1", code="300274"),
            StockPool(id="test-id-2", code="300750"),
        ]

        same_date = date.today() - timedelta(days=3)

        # 在数据库中插入相同的更新时间
        await memory_db.executemany(
            "INSERT INTO update_records (stock, key, update_time) VALUES (?, ?, ?)",
            [
                ("300274", "announcements", same_date.isoformat()),
                ("300750", "announcements", same_date.isoformat()),
            ],
        )
        await memory_db.commit()

        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann,
            patch(
                "core.announcements_data_handler.upload_files_with_url"
            ) as mock_upload_url,
            patch(
                "core.announcements_data_handler.upload_files_with_local"
            ) as mock_upload_local,
            patch("core.announcements_data_handler.create_dataflow_page"),
            patch("core.announcements_data_handler.split_pdf") as mock_split_pdf,
        ):
            mock_get_ann.return_value = []
            mock_upload_url.return_value = []
            mock_upload_local.return_value = []
            mock_split_pdf.return_value = []

            await process_announcements_data_for_stock_list(stock_list)

            # 验证：相同更新时间的股票应该被分组查询
            # 注意：实际逻辑中，无更新时间的股票会触发一次查询（空列表）
            # 有更新时间的股票按日期分组，相同日期的会一起查询
            # 所以这里应该至少有 1 次查询（分组查询）
            assert mock_get_ann.call_count >= 1

    async def test_empty_announcements_list(self, memory_db):
        """测试公告列表为空时的处理"""
        stock_list = [StockPool(id="test-page-id-123", code="300274")]

        with (
            patch("core.announcements_data_handler.get_announcements") as mock_get_ann,
            patch("core.announcements_data_handler.upload_files_with_url"),
            patch("core.announcements_data_handler.upload_files_with_local"),
            patch(
                "core.announcements_data_handler.create_dataflow_page"
            ) as mock_create_page,
            patch("core.announcements_data_handler.split_pdf"),
        ):
            mock_get_ann.return_value = []  # 空列表

            await process_announcements_data_for_stock_list(stock_list)

            # 验证：不应创建页面
            mock_create_page.assert_not_called()

            # 验证数据库中没有 hash 记录
            cursor = await memory_db.execute("SELECT COUNT(*) FROM hash")
            count = await cursor.fetchone()
            assert count[0] == 0


@pytest.mark.asyncio
class TestAnnouncementsIntegration:
    """集成测试：使用真实静态资源验证数据流"""

    async def test_static_resource_loading(self):
        """测试静态资源正确加载"""
        # 测试主营业务数据
        business_resource = resource_manager.load("ygdq_300274_business")
        assert business_resource.meta.name == "ygdq_300274_business"
        assert business_resource.meta.resource_type == ResourceType.DATAFRAME
        assert "300274" in business_resource.meta.tags

        business_df = business_resource.get_data()
        assert len(business_df) > 0
        assert "报告日期" in business_df.columns

        # 测试公告数据
        ann_resource = resource_manager.load("ygdq_300274_announcements")
        assert ann_resource.meta.name == "ygdq_300274_announcements"

        announcements = ann_resource.get_data()
        # 验证是列表类型
        assert isinstance(announcements, list)

        # 测试 API 响应数据
        response_resource = resource_manager.load("ygdq_300274_announcements_response")
        response_data = response_resource.get_data()
        assert isinstance(response_data, dict)

    async def test_split_keywords_detection(self):
        """测试分割关键词检测逻辑"""
        # 验证 SPLIT_KEYWORDS 包含预期关键词
        assert "年度报告" in SPLIT_KEYWORDS
        assert "年报" in SPLIT_KEYWORDS
        assert "中期" in SPLIT_KEYWORDS
