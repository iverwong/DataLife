import os
from dataclasses import dataclass
import logfire

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
    logfire.info("查询股票池数据源")
    try:
        raw_response = await notion.data_sources.query(stock_pool_id)  # pyright: ignore[reportAny]
        if not raw_response:
            logfire.error("获取股票池失败: 响应为空")
            raise Exception("获取股票池信息失败")

        response = QueryDataSourceResponse.model_validate(raw_response)

        if not response.results:
            logfire.warn("股票池为空")
            return []

        stock_pages: list[StockPool] = []
        for result in response.results:
            prop = result.properties.get("股票代码")
            if not isinstance(prop, RichTextPropertyResponse) or not prop.rich_text:
                logfire.warn(
                    "页面 {page_id} 的 '股票代码' 属性异常，已跳过", page_id=result.id
                )
                continue
            stock_pages.append(
                StockPool(id=result.id, code=prop.rich_text[0].plain_text or "")
            )

        logfire.info("获取股票池完成，共 {count} 只股票", count=len(stock_pages))
        return stock_pages
    except Exception:
        logfire.exception("获取股票池失败")
        raise
