"""公告数据获取与分组模块。

负责从数据库获取更新时间、按日期分组股票、并发获取公告数据。
"""

from collections.abc import Awaitable, Sequence
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta
import logfire

from core.utils import gather_with_concurrency_and_exceptions, get_cninfo_semaphore
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
    使用并发控制限制同时进行的 API 请求数量。

    Args:
        stock_list: 包含股票信息的列表。

    Returns:
        元组 (公告列表, 当天日期)。当天日期用于后续更新时间记录。
    """
    codes = [s.code for s in stock_list]
    logfire.info("开始获取公告数据，共 {count} 只股票", count=len(stock_list))

    update_times = await get_update_time(codes, "announcements")

    today = date.today()
    tasks: Sequence[Awaitable[list[Announcement]]] = []

    # 从未查询过的股票：从一年前开始
    init_stocks = [code for code, value in update_times.items() if value is None]
    if init_stocks:
        start_date = today - relativedelta(years=1)
        end_date = today + relativedelta(days=1)
        tasks.append(get_announcements(init_stocks, start_date, end_date))

    # 已有更新时间的股票：按日期分组合并查询
    group = defaultdict[date, list[str]](list)
    for code, value in update_times.items():
        if value is not None:
            update_date = convert_notion_date_to_datetime(value)
            group[update_date].append(code)

    for update_date, codes in group.items():
        start_date = update_date
        end_date = today + relativedelta(days=1)
        tasks.append(get_announcements(codes, start_date, end_date))

    if not tasks:
        logfire.info("无需查询公告")
        return [], today

    # 使用并发控制执行所有任务
    results = await gather_with_concurrency_and_exceptions(
        get_cninfo_semaphore(), tasks
    )

    # 展平结果，跳过异常
    announcements: list[Announcement] = []
    for result in results:
        if isinstance(result, BaseException):
            logfire.error(
                "获取公告异常: {error_type}", error_type=type(result).__name__
            )
            continue
        announcements.extend(result)

    logfire.info("公告获取完成，共 {count} 条", count=len(announcements))
    return announcements, today
