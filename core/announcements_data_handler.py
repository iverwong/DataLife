import asyncio
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from .data import get_announcements, split_pdf
from .db import get_update_time
from .notion import (
    FileUpload,
    StockPool,
    cover_notion_date_to_datetime,
    create_dataflow_page,
    upload_files_with_local,
    upload_files_with_url,
)

SPLIT_KEYWORDS = ["年度报告", "年报", "中期"]


async def process_announcements_data_for_stock_list(
    stock_list: list[StockPool],
) -> None:
    stocks_dict = {stock.code: stock.id for stock in stock_list}

    # 获取时间
    update_times = await get_update_time(
        [stock.code for stock in stock_list], "announcements"
    )

    # 该事件将作为最后更新时间
    today = date.today()

    # 对于更新时间为空的股票，默认从一年前开始
    init_update_stocks = [key for key, value in update_times.items() if value is None]

    start_date = today - relativedelta(years=1)
    end_date = today + relativedelta(days=1)

    tasks = [
        asyncio.create_task(get_announcements(init_update_stocks, start_date, end_date))
    ]

    # 对于有更新时间的股票，则分组完成（巨潮资讯网的接口可以同时查询多支股票，合并可以降低访问次数，对于日更的部分，可以每日只批量更一次）
    group: defaultdict[date, list[str]] = defaultdict(list)
    exist_update_stocks = {
        key: cover_notion_date_to_datetime(value)
        for key, value in update_times.items()
        if value is not None
    }
    for code, update in exist_update_stocks.items():
        group[update].append(code)

    for update, codes in group.items():
        start_date = update
        end_date = today + relativedelta(days=1)
        tasks.append(
            asyncio.create_task(get_announcements(codes, start_date, end_date))
        )

    # 执行获取公告信息tasks
    announcements_nested = await asyncio.gather(*tasks)
    announcements = [item for sublist in announcements_nested for item in sublist]

    # 上传附件
    file_uploads = [
        FileUpload(url=announcement.url, title=announcement.title)
        for announcement in announcements
        if announcement.size <= 1000
        or not any(kw in announcement.title for kw in SPLIT_KEYWORDS)
    ]

    # 外链上传任务
    extend_task = asyncio.create_task(upload_files_with_url(file_uploads))

    # 对大于涉及的附件进行分页
    file_need_split = [
        announcement
        for announcement in announcements
        if announcement.size > 1000
        and any(kw in announcement.title for kw in SPLIT_KEYWORDS)
    ]

    # 分割附件
    splited = split_pdf(file_need_split)
    # 分割后的公告已经包含了完整的FileUpload信息，直接使用
    internal_task = asyncio.create_task(upload_files_with_local(splited))

    # 上传至Notion
    external_uploaded, internal_uploaded = await asyncio.gather(
        extend_task, internal_task
    )
    uploaded = external_uploaded + internal_uploaded

    # 创建页面任务列表
    create_tasks = []

    # 创建数据流任务
    for i in range(len(announcements)):
        create_tasks.append(
            asyncio.create_task(
                create_dataflow_page(
                    title=announcements[i].title,
                    published_date=announcements[i].published_date,
                    source_api=f"{get_announcements.__module__}.{get_announcements.__name__}",
                    data_type="公告",
                    relation=stocks_dict[announcements[i].stock],
                    attachment_id=uploaded[i].get("file_id"),
                    source_url=announcements[i].url,
                    content=None,
                )
            )
        )

    await asyncio.gather(*create_tasks)
