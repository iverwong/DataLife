"""Tests for business_data_handler module.

Test Categories:
    - Unit tests: 测试单个函数，使用mock
    - Integration tests: 测试完整流程，使用真实调用
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, date
from pandas import DataFrame

from core.models import NotionDate
from core.notion.stock_pool import StockPool
from core.data.business import BusinessData
from tests.resource.manager import load_resource, ResourceType


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

        测试假设：
            - 函数能正确处理None值输入
            - None值表示从未更新过，应触发更新

        运行流程：
            1. 直接调用_should_update_half_year(None)
            2. 验证返回值为True

        预期结果：
            - 返回True，表示需要更新
        """
        from core.business_data_handler import _should_update_half_year

        # Act
        result = _should_update_half_year(None)

        # Assert
        assert result is True

    @pytest.mark.unit
    @pytest.mark.fast
    @patch("core.business_data_handler.datetime")
    async def test_should_update_half_year_q2_not_due(self, mock_datetime):
        """测试Q2结束但未到更新时间的情况.

        测试条件：
            - last_update_str为"2024-06-30"(Q2结束)
            - 当前时间为2024-08-01(未到次年1月)

        测试假设：
            - datetime.now()能被正确mock
            - Q2结束后应在次年1月1日更新

        运行流程：
            1. mock当前时间为2024-08-01
            2. 调用_should_update_half_year("2024-06-30")
            3. 验证返回值为False

        预期结果：
            - 返回False，表示不需要更新
        """
        from core.business_data_handler import _should_update_half_year

        # Arrange
        mock_datetime.now.return_value = datetime(2024, 8, 1)

        # Act
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

        测试假设：
            - 函数能正确解析日期并比较时间
            - 超过更新时间点应触发更新

        运行流程：
            1. 直接调用_should_update_half_year("2024-06-30")
            2. 验证返回值为True

        预期结果：
            - 返回True，表示需要更新
        """
        from core.business_data_handler import _should_update_half_year
        from core.models import NotionDate
        from freezegun import freeze_time

        # Arrange & Act & Assert
        # 使用freeze_time冻结时间到2025-01-01
        with freeze_time("2025-01-01"):
            result = _should_update_half_year(NotionDate("2024-06-30"))
            assert result is True

    @pytest.mark.unit
    @pytest.mark.fast
    @patch("core.business_data_handler.datetime")
    async def test_should_update_half_year_q4_not_due(self, mock_datetime):
        """测试Q4结束但未到更新时间的情况.

        测试条件：
            - last_update_str为"2024-12-31"(Q4结束)
            - 当前时间为2025-03-01(未到同年7月)

        测试假设：
            - Q4结束后应在次年7月1日更新

        运行流程：
            1. mock当前时间为2025-03-01
            2. 调用_should_update_half_year("2024-12-31")
            3. 验证返回值为False

        预期结果：
            - 返回False，表示不需要更新
        """
        from core.business_data_handler import _should_update_half_year

        # Arrange
        mock_datetime.now.return_value = datetime(2025, 3, 1)

        # Act
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

        测试假设：
            - 函数能正确解析日期并比较时间
            - 超过Q4更新时间点应触发更新

        运行流程：
            1. 直接调用_should_update_half_year("2024-12-31")
            2. 验证返回值为True

        预期结果：
            - 返回True，表示需要更新
        """
        from core.business_data_handler import _should_update_half_year
        from core.models import NotionDate
        from freezegun import freeze_time

        # Arrange & Act & Assert
        # 使用freeze_time冻结时间到2025-07-01
        with freeze_time("2025-07-01"):
            result = _should_update_half_year(NotionDate("2024-12-31"))
            assert result is True

    @pytest.mark.unit
    @pytest.mark.fast
    @patch("core.business_data_handler.logger")
    async def test_should_update_half_year_invalid_date(self, mock_logger):
        """测试非季度末日期的情况.

        测试条件：
            - 输入非季度末日期"2024-03-15"

        测试假设：
            - 函数应记录warning日志
            - 对于无效日期应返回False

        运行流程：
            1. 调用_should_update_half_year("2024-03-15")
            2. 验证返回值为False
            3. 验证记录了warning日志

        预期结果：
            - 返回False
            - 记录相应的warning日志
        """
        from core.business_data_handler import _should_update_half_year

        # Act
        result = _should_update_half_year(NotionDate("2024-03-15"))

        # Assert
        assert result is False
        mock_logger.warning.assert_called_once()


class TestProcessBusinessDataForStockList:
    """测试process_business_data_for_stock_list主函数."""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_process_business_data_empty_stock_list(self, in_memory_db):
        """测试空股票列表的处理.

        测试条件：
            - 输入空的股票列表[]

        测试假设：
            - 函数应对空列表进行适当处理
            - 不应抛出异常

        运行流程：
            1. 准备空的股票列表
            2. 调用process_business_data_for_stock_list([])
            3. 验证函数正常返回

        预期结果：
            - 函数成功执行并返回None
            - 不调用任何外部依赖
        """
        from core.business_data_handler import process_business_data_for_stock_list

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

        测试假设：
            - get_update_time能正确返回更新时间
            - _should_update_half_year能正确判断不需要更新

        运行流程：
            1. mock get_update_time返回近期更新时间
            2. mock _should_update_half_year返回False
            3. 调用process_business_data_for_stock_list
            4. 验证不调用get_business

        预期结果：
            - 不调用get_business等后续依赖
            - 函数正常返回
        """
        from core.business_data_handler import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {
            "000001": "2024-06-30",
            "000002": "2024-06-30",
            "600000": "2024-06-30",
        }

        with (
            patch(
                "core.business_data_handler.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch(
                "core.business_data_handler._should_update_half_year",
                return_value=False,
            ) as mock_should_update,
        ):
            # Act
            result = await process_business_data_for_stock_list(sample_stock_list)

            # Assert
            assert result is None
            # 验证_should_update_half_year被调用了3次(每个股票一次)
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

        测试假设：
            - get_business能正确返回业务数据
            - check_hash能正确识别重复数据

        运行流程：
            1. mock所有前置依赖返回需要更新的状态
            2. mock check_hash返回空列表
            3. mock akshare返回静态资源数据
            4. 调用process_business_data_for_stock_list
            5. 验证不调用create_dataflow_page

        预期结果：
            - 不创建Notion页面
            - 不保存哈希和更新时间
            - 函数正常返回
        """
        from core.business_data_handler import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"000001": None}

        with (
            patch(
                "core.business_data_handler.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch(
                "core.business_data_handler._should_update_half_year", return_value=True
            ),
            patch(
                "akshare.stock_zygc_em",  # mock akshare的网络调用
                return_value=mock_akshare_response,
            ),
            patch(
                "core.business_data_handler.check_hash",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "core.business_data_handler.create_dataflow_page",
                new_callable=AsyncMock,
            ) as mock_create_page,
        ):
            # Act
            result = await process_business_data_for_stock_list([sample_stock_list[0]])

            # Assert
            assert result is None
            # 验证没有调用创建页面
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

        测试假设：
            - 所有mock依赖能正确工作
            - NotionContentBuilder能正确构建内容

        运行流程：
            1. mock所有依赖返回成功响应
            2. 调用process_business_data_for_stock_list
            3. 验证调用顺序和参数正确

        预期结果：
            - 成功调用create_dataflow_page
            - 成功调用save_hash和set_update_time
            - 函数正常返回
        """
        from core.business_data_handler import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"000001": None}
        mock_hash_result = [{"hash": "test_hash_123"}]

        with (
            patch(
                "core.business_data_handler.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch(
                "core.business_data_handler._should_update_half_year", return_value=True
            ),
            patch(
                "akshare.stock_zygc_em",  # mock akshare的网络调用
                return_value=mock_akshare_response,
            ),
            patch(
                "core.business_data_handler.check_hash",
                new_callable=AsyncMock,
                return_value=mock_hash_result,
            ),
            patch(
                "core.business_data_handler.create_dataflow_page",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_create_page,
            patch(
                "core.business_data_handler.save_hash", new_callable=AsyncMock
            ) as mock_save_hash,
            patch(
                "core.business_data_handler.set_update_time", new_callable=AsyncMock
            ) as mock_set_update_time,
        ):
            # Act
            result = await process_business_data_for_stock_list([sample_stock_list[0]])

            # Assert
            assert result is None

            # 验证create_dataflow_page被正确调用
            mock_create_page.assert_called_once()
            call_args = mock_create_page.call_args[1]
            assert call_args["title"] == "000001-2025-06-30-主营构成"
            assert call_args["published_date"] == date(2025, 6, 30)
            assert call_args["source_api"] == "core.data.business.get_business"
            assert call_args["data_type"] == "主营构成"
            assert call_args["relation"] == "page1"

            # 验证save_hash被调用
            mock_save_hash.assert_called_once_with(["test_hash_123"])

            # 验证set_update_time被调用
            mock_set_update_time.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.fast
    @patch("core.business_data_handler.logger")
    async def test_process_business_data_create_failure(
        self, mock_logger, sample_stock_list_300274, mock_akshare_response, in_memory_db
    ):
        """测试创建Notion页面失败的情况.

        测试条件：
            - create_dataflow_page返回False

        测试假设：
            - 页面创建失败时不应保存哈希和更新时间
            - 应记录相应的错误日志

        运行流程：
            1. mock create_dataflow_page返回False
            2. 调用process_business_data_for_stock_list
            3. 验证不调用save_hash和set_update_time
            4. 验证记录了错误日志

        预期结果：
            - 不保存哈希和更新时间
            - 记录"创建300274-主营业务构成数据流页面失败"错误日志
            - 函数正常返回
        """
        from core.business_data_handler import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"300274": None}  # 使用300274股票代码
        mock_hash_result = [{"hash": "test_hash_123"}]

        with (
            patch(
                "core.business_data_handler.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch(
                "core.business_data_handler._should_update_half_year", return_value=True
            ),
            patch(
                "akshare.stock_zygc_em",  # mock akshare的网络调用
                return_value=mock_akshare_response,
            ),
            patch(
                "core.business_data_handler.check_hash",
                new_callable=AsyncMock,
                return_value=mock_hash_result,
            ),
            patch(
                "core.business_data_handler.create_dataflow_page",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_create_page,
            patch(
                "core.business_data_handler.save_hash", new_callable=AsyncMock
            ) as mock_save_hash,
            patch(
                "core.business_data_handler.set_update_time", new_callable=AsyncMock
            ) as mock_set_update_time,
        ):
            # Act
            result = await process_business_data_for_stock_list(
                [sample_stock_list_300274[0]]
            )

            # Assert
            assert result is None
            # 验证没有保存哈希和更新时间
            mock_save_hash.assert_not_called()
            mock_set_update_time.assert_not_called()

            # 验证记录了错误日志
            # 验证create_dataflow_page被正确调用
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

        测试假设：
            - 异常应向上传播而不被吞掉

        运行流程：
            1. mock get_business抛出异常
            2. 调用process_business_data_for_stock_list
            3. 验证异常被正确传播

        预期结果：
            - 原始异常被重新抛出
        """
        from core.business_data_handler import process_business_data_for_stock_list

        # Arrange
        mock_update_times = {"000001": None}

        with (
            patch(
                "core.business_data_handler.get_update_time",
                new_callable=AsyncMock,
                return_value=mock_update_times,
            ),
            patch(
                "core.business_data_handler._should_update_half_year", return_value=True
            ),
            patch(
                "akshare.stock_zygc_em",  # mock akshare的网络调用失败
                side_effect=Exception("API error"),
            ),
        ):
            # Act & Assert
            with pytest.raises(Exception, match="API error"):
                await process_business_data_for_stock_list([sample_stock_list[0]])


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.real_network
async def test_integration_real_flow(test_env):
    """测试真实完整流程（使用.dev.env配置）.

    测试条件：
        - 真实的网络环境可用
        - .dev.env中的Notion API凭据配置正确
        - 可以访问真实的AkShare API

    测试假设：
        - Notion API服务正常运行
        - AkShare接口可访问
        - 网络连接稳定
        - 测试环境变量已正确加载

    运行流程：
        1. 加载真实的测试环境配置(.dev.env)
        2. 准备测试用的股票列表
        3. 执行完整的端到端业务流程
        4. 验证最终结果符合预期

    预期结果：
        - 整个业务流程成功执行
        - 返回None（函数无返回值）
        - 在Notion中成功创建页面（可通过手动检查验证）
    """
    from core.business_data_handler import process_business_data_for_stock_list
    from core.notion.stock_pool import StockPool

    # 验证环境变量加载成功
    assert test_env["NOTION_TOKEN"] is not None
    assert test_env["FLOW_DATABASE"] is not None
    assert test_env["STOCK_POOL"] is not None

    # 准备测试数据 - 使用少量真实股票代码
    test_stock_list = [
        StockPool(id="test_page_1", code="000001"),  # 平安银行
    ]

    # 执行真实流程
    result = await process_business_data_for_stock_list(test_stock_list)

    # 验证结果
    assert result is None  # 函数无返回值
