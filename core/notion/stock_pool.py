import logging
import os
from typing import NamedTuple

from . import notion

logger = logging.getLogger(__name__)


class StockPool(NamedTuple):
    """
    定义一个名为StockPool的命名元组类，用于表示股票池中的股票信息。

    属性:
        id (str): 股票的唯一标识符。
        code (str): 股票的代码。
    """

    id: str
    code: str


async def get_stock_pool() -> list[StockPool]:
    """
    异步函数：从Notion数据源获取股票池信息并返回StockPool对象列表。

    该函数通过查询Notion数据库中的股票池数据，提取每只股票的ID和代码，
    并将其封装为StockPool对象列表返回。如果过程中发生异常，则记录错误日志并重新抛出异常。

    返回值:
        list[StockPool]: 包含股票ID和代码的StockPool对象列表。
    """
    stock_pool_id = os.getenv("STOCK_POOL") or ""

    logger.info("获取股票池")
    try:
        response = await notion.data_sources.query(stock_pool_id)
        results = response.get("results", [])  # type: ignore
        stock_ids: list[str] = [result["id"] for result in results]
        stock_codes: list[str] = [
            result["properties"]["股票代码"]["rich_text"][0]["plain_text"]
            for result in results
        ]
        stock_pages = [
            StockPool(id=id, code=code) for id, code in zip(stock_ids, stock_codes)
        ]
        logger.info(f"成功获取到 {len(stock_ids)} 个股票信息")
        return stock_pages
    except Exception as e:
        logger.error(f"获取股票池失败: {e}")
        raise
