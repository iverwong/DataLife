import os
from dataclasses import dataclass
from loguru import logger

from .client import notion
from .models import QueryDataSourceResponse, RichTextPropertyResponse
from .retry_helper import with_retry


@dataclass(frozen=True)
class StockPool:
    """表示股票池中的股票信息。

    Attributes:
        id: 股票的唯一标识符（Notion 页面 ID）。
        code: 股票的代码。
    """

    id: str
    code: str


@with_retry()
async def get_stock_pool() -> list[StockPool]:
    """从Notion数据源获取股票池信息并返回StockPool对象列表。

    Returns:
        包含股票ID和代码的StockPool对象列表。

    Raises:
        Exception: 获取股票池信息失败时抛出。
    """
    stock_pool_id = os.getenv("STOCK_POOL") or ""
    logger.info("开始获取股票池", stock_pool_id=stock_pool_id)
    try:
        notion_logger = logger.bind(
            request="notion.data_sources.query", data_source_id=stock_pool_id
        )
        notion_logger.info("查询Notion数据库以获取股票池信息")
        raw_response = await notion.data_sources.query(stock_pool_id)  # pyright: ignore[reportAny]
        if not raw_response:
            notion_logger.error("获取股票池信息失败", response=raw_response)
            raise Exception("获取股票池信息失败")

        response = QueryDataSourceResponse.model_validate(raw_response)
        notion_logger.success("成功获取股票池信息")

        if not response.results:
            notion_logger.warning("未获取到任何股票信息")
            return []

        stock_pages: list[StockPool] = []
        for result in response.results:
            prop = result.properties.get("股票代码")
            if not isinstance(prop, RichTextPropertyResponse) or not prop.rich_text:
                notion_logger.warning(
                    f"页面 {result.id} 的 '股票代码' 属性类型异常，已跳过"
                )
                continue
            stock_pages.append(
                StockPool(id=result.id, code=prop.rich_text[0].plain_text or "")
            )

        logger.success(f"成功获取到 {len(stock_pages)} 个股票信息")
        return stock_pages
    except Exception as e:
        logger.exception(f"获取股票池失败: {e}")
        raise
