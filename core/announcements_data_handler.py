from core.data.announcement import Announcement
from core.db import HashContentWithHash

import asyncio

from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta
from loguru import logger

from core.notion.upload_file import FileUploadWithContent, FileUploaded

from .data import get_announcements, split_pdf
from .db import HashContent, check_hash, get_update_time, save_hash, set_update_time
from .notion import (
    FileUpload,
    StockPool,
    cover_datetime_to_notion_date,
    cover_notion_date_to_datetime,
    create_dataflow_page,
    upload_files_with_local,
    upload_files_with_url,
)

SPLIT_KEYWORDS = ["年度报告", "年报", "中期"]


async def process_announcements_data_for_stock_list(
    stock_list: list[StockPool],
) -> None:
    task_logger = logger.bind(stock_list=[stock.code for stock in stock_list])
    task_logger.info("开始处理股票列表中的公告数据")
    stocks_dict = {stock.code: stock.id for stock in stock_list}

    # 获取更新时间
    update_times = await get_update_time(
        [stock.code for stock in stock_list], "announcements"
    )

    # 该事件将作为最后更新时间
    today = date.today()

    # 初始化tasks
    tasks: list[asyncio.Task[list[Announcement]]] = []

    # 对于更新时间为空的股票，默认从一年前开始
    init_update_stocks = [key for key, value in update_times.items() if value is None]
    if init_update_stocks:
        start_date = today - relativedelta(years=1)
        end_date = today + relativedelta(days=1)

        tasks = [
            asyncio.create_task(
                get_announcements(init_update_stocks, start_date, end_date)
            )
        ]

    # 对于有更新时间的股票，则分组完成（巨潮资讯网的接口可以同时查询多支股票，合并可以降低访问次数，对于日更的部分，可以每日只批量更一次）
    group = defaultdict[date, list[str]](list)
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
    task_logger.success("所有股票公告信息获取完成")
    announcements = [item for sublist in announcements_nested for item in sublist]

    # 如果没有获取到任何公告，直接返回
    if not announcements:
        task_logger.info("没有获取到任何公告，跳过处理")
        return

    # 构建去重内容列表
    hash_contents: list[HashContent] = [
        HashContent(
            data_type="announcements",
            content=f"{ann.stock}-{ann.id}-{ann.title}",
        )
        for ann in announcements
    ]

    # 检查 hash 去重
    # check_hash 会返回新列表，包含 hash 字段，仅包含未存在的元素
    filtered_hash_contents: list[HashContentWithHash] = await check_hash(hash_contents)
    task_logger.info(
        "公告数据增量更新，去重前{}, 去重后{}",
        len(hash_contents),
        len(filtered_hash_contents),
    )

    # 如果所有公告都已存在，直接返回
    if not filtered_hash_contents:
        task_logger.info("所有公告都已存在，跳过处理")
        return

    # 构建需要保留的 content 集合
    filtered_contents = {item["content"] for item in filtered_hash_contents}

    # 过滤公告列表：只保留 content 在 filtered_contents 中的公告
    filtered_announcements: list[tuple[Announcement, str]] = [
        (ann, hc["content"])
        for ann, hc in zip(announcements, hash_contents)
        if hc["content"] in filtered_contents
    ]

    # hash和content对照表
    hash_content_map = {
        each["content"]: each["hash"] for each in filtered_hash_contents
    }

    # 更新变量指向
    announcements = [
        (each[0], hash_content_map[each[1]]) for each in filtered_announcements
    ]

    # 上传附件
    file_uploads = [
        FileUpload(
            url=announcement[0].url,
            title=announcement[0].title,
            stock=announcement[0].stock,
            published_date=announcement[0].published_date,
            hash_content=announcement[1],
        )
        for announcement in announcements
        if announcement[0].size <= 1000
        or not any(kw in announcement[0].title for kw in SPLIT_KEYWORDS)
    ]

    # 外链上传任务
    external_task = asyncio.create_task(upload_files_with_url(file_uploads))

    # 对大于涉及的附件进行分页
    file_need_split = [
        announcement
        for announcement in announcements
        if announcement[0].size > 1000
        and any(kw in announcement[0].title for kw in SPLIT_KEYWORDS)
    ]

    # 分割附件
    splited = split_pdf(file_need_split)
    # 将分割后的 Announcement 对象转换为 FileUpload 格式
    splited_file_uploads = [
        FileUploadWithContent(
            url=announcement[0].url,
            title=announcement[0].title,
            stock=announcement[0].stock,
            published_date=announcement[0].published_date,
            content=announcement[0].content,
            hash_content=announcement[1],
        )
        for announcement in splited
    ]
    internal_task = asyncio.create_task(upload_files_with_local(splited_file_uploads))

    # 上传至Notion
    external_uploaded, internal_uploaded = await asyncio.gather(
        external_task, internal_task
    )

    # 外部附件筛选
    external: list[FileUploaded] = [
        item for item in external_uploaded if item["successed"]
    ]

    # 失败附件
    failed: list[FileUploaded] = [
        each for each in external_uploaded if not each["successed"]
    ]

    # 本地附件筛选
    internal: list[FileUploaded] = []

    # 失败的附件筛选

    # 筛选所有的附件
    set_hash_content = {each["hash_content"] for each in internal_uploaded}
    # 判断是否所有的都成功
    for each_hash in set_hash_content:
        hash_group = [
            each for each in internal_uploaded if each["hash_content"] == each_hash
        ]
        if all(item["successed"] for item in hash_group):
            internal.extend(hash_group)
        else:
            failed.extend(hash_group)
    if failed:
        task_logger.error(f"上传失败附件：{failed}")

    uploaded: list[FileUploaded] = external + internal

    # 创建页面任务列表
    create_tasks: list[asyncio.Task[bool]] = []

    # 创建数据流任务
    for each in uploaded:
        create_tasks.append(
            asyncio.create_task(
                create_dataflow_page(
                    title=each["title"],
                    published_date=each["published_date"],
                    source_api=f"{get_announcements.__module__}.{get_announcements.__name__}",
                    data_type="公告披露",
                    relation=stocks_dict[each["stock"]],
                    attachment_id=each["file_id"],
                    source_url=each["url"],
                    content=None,
                )
            )
        )

    # 收集创建结果
    create_results = await asyncio.gather(*create_tasks)

    success_hash_contents = [
        uploaded[i] for i, success in enumerate(create_results) if success
    ]

    if success_hash_contents:
        # 去重：PDF分割的多个部分有相同的hash_content，只保存一次
        unique_hash_contents = list(
            {each["hash_content"] for each in success_hash_contents}
        )
        await save_hash(unique_hash_contents)
        task_logger.info(f"成功创建 {len(success_hash_contents)} 条公告页面")

    # 统计失败数量
    failed_count = len(create_results) - len(success_hash_contents)
    if failed_count > 0:
        task_logger.error(f"创建失败 {failed_count} 条公告页面")

    # 更新每只股票的最后更新时间
    for stock_code in set(ann[0].stock for ann in announcements):
        await set_update_time(
            stock_code,
            "announcements",
            update_time=cover_datetime_to_notion_date(today),
        )
