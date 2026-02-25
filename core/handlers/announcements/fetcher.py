"""公告数据获取与分组模块。

负责从数据库获取更新时间、按日期分组股票、并发获取公告数据。
"""

import asyncio
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta
from loguru import logger

from core.data.announcement import Announcement
from core.db import get_update_time
from core.notion.datetime_helper import convert_notion_date_to_datetime
from core.notion.stock_pool import StockPool
from core.data import get_announcements


async def fetch_announcements_for_stocks(
    stock_list: list[StockPool],
) -> tuple[list[Announcement], date]:
    """获取股票列表的公告数据，按更新时间分组以减少 API 调用。

    对于从未查询过的股票，默认从一年前开始查询；
    对于已有更新时间的股票，按更新日期分组合并查询。

    Args:
        stock_list: 包含股票信息的列表。

    Returns:
        元组 (公告列表, 当天日期)。当天日期用于后续更新时间记录。
    """
    task_logger = logger.bind(stock_list=[s.code for s in stock_list])
    task_logger.info("开始获取股票列表的公告数据")

    update_times = await get_update_time(
        [stock.code for stock in stock_list], "announcements"
    )

    today = date.today()
    tasks: list[asyncio.Task[list[Announcement]]] = []

    # 从未查询过的股票：从一年前开始
    init_stocks = [code for code, value in update_times.items() if value is None]
    if init_stocks:
        start_date = today - relativedelta(years=1)
        end_date = today + relativedelta(days=1)
        tasks.append(
            asyncio.create_task(get_announcements(init_stocks, start_date, end_date))
        )

    # 已有更新时间的股票：按日期分组合并查询
    group = defaultdict[date, list[str]](list)
    for code, value in update_times.items():
        if value is not None:
            update_date = convert_notion_date_to_datetime(value)
            group[update_date].append(code)

    for update_date, codes in group.items():
        start_date = update_date
        end_date = today + relativedelta(days=1)
        tasks.append(
            asyncio.create_task(get_announcements(codes, start_date, end_date))
        )

    if not tasks:
        task_logger.info("没有需要查询的公告任务")
        return [], today

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 展平结果，跳过异常
    announcements: list[Announcement] = []
    for result in results:
        if isinstance(result, BaseException):
            task_logger.error("获取公告数据时发生异常: {}", result)
            continue
        announcements.extend(result)

    task_logger.success("所有股票公告信息获取完成，共{}条", len(announcements))
    return announcements, today
