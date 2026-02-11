import os
from typing import NamedTuple

from loguru import logger

from . import notion
from .retry_helper import with_retry


class StockPool(NamedTuple):
    """
    定义一个名为StockPool的命名元组类，用于表示股票池中的股票信息。

    属性:
        id (str): 股票的唯一标识符。
        code (str): 股票的代码。
    """

    id: str
    code: str


@with_retry()
async def get_stock_pool() -> list[StockPool]:
    """
    异步函数：从Notion数据源获取股票池信息并返回StockPool对象列表。

    该函数通过查询Notion数据库中的股票池数据，提取每只股票的ID和代码，
    并将其封装为StockPool对象列表返回。如果过程中发生异常，则记录错误日志并重新抛出异常。

    返回值:
        list[StockPool]: 包含股票ID和代码的StockPool对象列表。
        raise Exception("获取股票池信息失败")
    """
    stock_pool_id = os.getenv("STOCK_POOL") or ""
    logger.info("开始获取股票池", stock_pool_id=stock_pool_id)
    try:
        notion_logger = logger.bind(
            request="notion.data_sources.query", data_source_id=stock_pool_id
        )
        notion_logger.info("查询Notion数据库以获取股票池信息")
        response = await notion.data_sources.query(stock_pool_id)
        if response:
            notion_logger.success("成功获取股票池信息", response=response)
        else:
            notion_logger.error("获取股票池信息失败", response=response)
            raise Exception("获取股票池信息失败")
        results = response.get("results")
        if results:
            stock_ids: list[str] = [result["id"] for result in results]
            stock_codes: list[str] = [
                result["properties"]["股票代码"]["rich_text"][0]["plain_text"]
                for result in results
            ]
            stock_pages = [
                StockPool(id=id, code=code) for id, code in zip(stock_ids, stock_codes)
            ]
            logger.success(f"成功获取到 {len(stock_ids)} 个股票信息")
            return stock_pages
        else:
            notion_logger.warning("未获取到任何股票信息", response=response)
            return []
    except Exception as e:
        logger.exception(f"获取股票池失败: {e}")
        raise
