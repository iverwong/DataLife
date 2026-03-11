"""Tests for business handler module.

Test Categories:
    - Unit tests: 测试单个函数，使用mock
    - Integration tests: 测试完整流程，使用真实调用
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from pandas import DataFrame

from core.db import HashContentWithHash
from core.models import NotionDate
from core.notion.stock_pool import StockPool
from tests.resource.manager import load_resource

# 标记所有测试为异步
pytestmark = pytest.mark.asyncio


@pytest.fixture
def sample_stock_list_300274():
    """提供测试用的300274股票列表（与静态资源匹配）."""
    return [
        StockPool(id="page_ygdq", code="300274"),
    ]


@pytest.fixture
def sample_stock_list():
    """提供测试用的股票列表."""
    return [
        StockPool(id="page1", code="000001"),
        StockPool(id="page2", code="000002"),
        StockPool(id="page3", code="600000"),
    ]


@pytest.fixture
def mock_akshare_response():
    """提供akshare接口的mock响应数据（来自静态资源）."""
    # 从静态资源加载akshare的原始响应数据
    resource = load_resource("ygdq_300274_business", DataFrame)
    return resource.data


class TestShouldUpdateHalfYear:
    """测试_should_update_half_year辅助函数."""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_should_update_half_year_none(self):
        """测试last_update_str为None的情况.

        测试条件：
            - 输入last_update_str为None

        预期结果：
            - 返回True，表示需要更新
        """
        from core.handlers.business import _should_update_half_year

        # Act
        result = _should_update_half_year(None)

        # Assert
        assert result is True

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_should_update_half_year_q2_not_due(self):
        """测试Q2结束但未到更新时间的情况.

        测试条件：
            - last_update_str为"2024-06-30"(Q2结束)
            - 当前时间为2024-08-01(未到次年1月)

        预期结果：
            - 返回False，表示不需要更新
        """
        from freezegun import freeze_time

        from core.handlers.business import _should_update_half_year

        with freeze_time("2024-08-01"):
            result = _should_update_half_year(NotionDate("2024-06-30"))

        # Assert
        assert result is False

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_should_update_half_year_q2_due(self):
        """测试Q2结束且已到更新时间的情况.

        测试条件：
            - last_update_str为"2024-06-30"(Q2结束)
            - 当前时间为2025-01-01(正好是次年1月1日)

        预期结果：
            - 返回True，表示需要更新
        """
        from freezegun import freeze_time

        from core.handlers.business import _should_update_half_year
        from core.models import NotionDate

        with freeze_time("2025-01-01"):
            result = _should_update_half_year(NotionDate("2024-06-30"))
            assert result is True

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_should_update_half_year_q4_not_due(self):
        """测试Q4结束但未到更新时间的情况.

        测试条件：
            - last_update_str为"2024-12-31"(Q4结束)
            - 当前时间为2025-03-01(未到同年7月)

        预期结果：
            - 返回False，表示不需要更新
        """
        from freezegun import freeze_time

        from core.handlers.business import _should_update_half_year

        with freeze_time("2025-03-01"):
            result = _should_update_half_year(NotionDate("2024-12-31"))

        # Assert
        assert result is False

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_should_update_half_year_q4_due(self):
        """测试Q4结束且已到更新时间的情况.

        测试条件：
            - last_update_str为"2024-12-31"(Q4结束)
            - 当前时间为2025-07-01(正好是次年7月1日)

        预期结果：
            - 返回True，表示需要更新
        """
        from freezegun import freeze_time

        from core.handlers.business import _should_update_half_year
        from core.models import NotionDate

        with freeze_time("2025-07-01"):
            result = _should_update_half_year(NotionDate("2024-12-31"))
            assert result is True

    @pytest.mark.unit
    @pytest.mark.fast
    @patch("logfire.warn")
    def test_should_update_half_year_invalid_date(self, mock_warn):
        """测试非季度末日期的情况.

        测试条件：
            - 输入非季度末日期"2024-03-15"

        预期结果：
            - 返回False
            - 记录相应的warning日志
        """
        from core.handlers.business import _should_update_half_year

        # Act
        result = _should_update_half_year(NotionDate("2024-03-15"))

        # Assert
        assert result is False
        mock_warn.assert_called_once()


class TestProcessBusinessDataForStockList:
    """测试process_business_data_for_stock_list主函数."""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_empty_stock_list(self, in_memory_db):
        """测试空股票列表的处理.

        预期结果：
            - 函数成功执行并返回None
            - 不调用任何外部依赖
        """
        from core.handlers.business import process_business_data_for_stock_list

        # Act & Assert
        result = await process_business_data_for_stock_list([])

        # Assert
        assert result is None

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_no_update_needed(
        self, sample_stock_list, in_memory_db
    ):
        """测试不需要更新的情况.

        测试条件：
            - 股票更新时间为近期季度末
            - _should_update_half_year返回False

        预期结果：
            - 不调用get_business等后续依赖
            - 函数正常返回
        """
        from core.handlers.business import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {
            "000001": "2024-06-30",
            "000002": "2024-06-30",
            "600000": "2024-06-30",
        }

        with (
            patch(
                "core.handlers.business.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch(
                "core.handlers.business._should_update_half_year",
                return_value=False,
            ) as mock_should_update,
        ):
            # Act
            result = await process_business_data_for_stock_list(sample_stock_list)

            # Assert
            assert result is None
            assert mock_should_update.call_count == 3

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_data_exists(
        self, sample_stock_list, mock_akshare_response, in_memory_db
    ):
        """测试数据已存在的情况.

        测试条件：
            - 需要更新(should_update返回True)
            - 但check_hash返回空列表(数据已存在)

        预期结果：
            - 不创建Notion页面
            - 函数正常返回
        """
        from core.handlers.business import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"000001": None}

        with (
            patch(
                "core.handlers.business.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch("core.handlers.business._should_update_half_year", return_value=True),
            patch(
                "akshare.stock_zygc_em",
                return_value=mock_akshare_response,
            ),
            patch(
                "core.handlers.business.check_hash",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "core.handlers.business.create_dataflow_page",
                new_callable=AsyncMock,
            ) as mock_create_page,
        ):
            # Act
            result = await process_business_data_for_stock_list([sample_stock_list[0]])

            # Assert
            assert result is None
            mock_create_page.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_create_success(
        self, sample_stock_list, mock_akshare_response, in_memory_db
    ):
        """测试成功创建Notion页面的情况.

        测试条件：
            - 所有前置条件满足
            - create_dataflow_page返回True

        预期结果：
            - 成功调用create_dataflow_page
            - 成功调用save_hash和set_update_time
        """
        from core.handlers.business import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"000001": None}
        mock_hash_result = [
            HashContentWithHash(
                data_type="business",
                content="test_content",
                hash_value="test_hash_123",
            )
        ]

        with (
            patch(
                "core.handlers.business.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch("core.handlers.business._should_update_half_year", return_value=True),
            patch(
                "akshare.stock_zygc_em",
                return_value=mock_akshare_response,
            ),
            patch(
                "core.handlers.business.check_hash",
                new_callable=AsyncMock,
                return_value=mock_hash_result,
            ),
            patch(
                "core.handlers.business.create_dataflow_page",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_create_page,
            patch(
                "core.handlers.business.save_hash", new_callable=AsyncMock
            ) as mock_save_hash,
            patch(
                "core.handlers.business.set_update_time", new_callable=AsyncMock
            ) as mock_set_update_time,
        ):
            # Act
            result = await process_business_data_for_stock_list([sample_stock_list[0]])

            # Assert
            assert result is None

            mock_create_page.assert_called_once()
            call_args = mock_create_page.call_args[1]
            assert call_args["title"] == "000001-2025-06-30-主营构成"
            assert call_args["published_date"] == date(2025, 6, 30)
            assert call_args["source_api"] == "core.data.business.get_business"
            assert call_args["data_type"] == "主营构成"
            assert call_args["relation"] == "page1"

            mock_save_hash.assert_called_once_with(["test_hash_123"])
            mock_set_update_time.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_create_failure(
        self, sample_stock_list_300274, mock_akshare_response, in_memory_db
    ):
        """测试创建Notion页面失败的情况.

        测试条件：
            - create_dataflow_page返回False

        预期结果：
            - 不保存哈希和更新时间
            - 函数正常返回
        """
        from core.handlers.business import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"300274": None}
        mock_hash_result = [
            HashContentWithHash(
                data_type="business",
                content="test_content",
                hash_value="test_hash_123",
            )
        ]

        with (
            patch(
                "core.handlers.business.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch("core.handlers.business._should_update_half_year", return_value=True),
            patch(
                "akshare.stock_zygc_em",
                return_value=mock_akshare_response,
            ),
            patch(
                "core.handlers.business.check_hash",
                new_callable=AsyncMock,
                return_value=mock_hash_result,
            ),
            patch(
                "core.handlers.business.create_dataflow_page",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_create_page,
            patch(
                "core.handlers.business.save_hash", new_callable=AsyncMock
            ) as mock_save_hash,
            patch(
                "core.handlers.business.set_update_time", new_callable=AsyncMock
            ) as mock_set_update_time,
        ):
            # Act
            result = await process_business_data_for_stock_list(
                [sample_stock_list_300274[0]]
            )

            # Assert
            assert result is None
            mock_save_hash.assert_not_called()
            mock_set_update_time.assert_not_called()

            mock_create_page.assert_called_once()
            call_args = mock_create_page.call_args[1]
            assert call_args["title"] == "300274-2025-06-30-主营构成"

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_get_business_error(
        self, sample_stock_list, mock_akshare_response, in_memory_db
    ):
        """测试get_business抛出异常的情况.

        测试条件：
            - get_business调用抛出异常

        预期结果：
            - 异常被捕获并记录日志，函数继续处理下一只股票
            - 不抛出异常
        """
        from core.handlers.business import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"000001": None}

        with (
            patch(
                "core.handlers.business.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch("core.handlers.business._should_update_half_year", return_value=True),
            patch(
                "akshare.stock_zygc_em",
                side_effect=Exception("API error"),
            ),
        ):
            # Act - 不应抛出异常，而是记录日志并跳过
            result = await process_business_data_for_stock_list([sample_stock_list[0]])

            # Assert
            assert result is None


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.real_network
async def test_integration_real_flow(test_env, test_engine):
    """测试真实完整流程（使用.dev.env配置）.

    测试条件：
        - 真实的网络环境可用
        - .dev.env中的Notion API凭据配置正确

    预期结果：
        - 整个业务流程成功执行
        - 返回None（函数无返回值）
    """
    from core.handlers.business import process_business_data_for_stock_list
    from core.notion.stock_pool import StockPool

    assert test_env["NOTION_TOKEN"] is not None
    assert test_env["FLOW_DATABASE"] is not None
    assert test_env["STOCK_POOL"] is not None

    test_stock_list = [
        StockPool(id="test_page_1", code="000001"),
    ]

    result = await process_business_data_for_stock_list(test_stock_list)
    assert result is None
