"""公告数据处理编排模块。

协调数据获取、去重、上传和页面创建的完整流程，
将股票公告从巨潮资讯网采集并同步到 Notion 资讯流数据库。
"""

import logfire

from core.db import save_hash, set_update_time
from core.notion.datetime_helper import convert_datetime_to_notion_date
from core.notion.stock_pool import StockPool

from .deduplicator import deduplicate_announcements
from .fetcher import fetch_announcements_for_stocks
from .page_creator import create_announcement_pages
from .uploader import upload_announcement_files


async def process_announcements_for_stock_list(
    stock_list: list[StockPool],
) -> None:
    """公告数据处理主流程编排。

    完整流程：获取公告 -> 哈希去重 -> 文件上传 -> 创建 Notion 页面 -> 记录哈希和更新时间。

    Args:
        stock_list: 待处理的股票列表。
    """
    codes = [s.code for s in stock_list]
    with logfire.span("process_announcements", stock_codes=codes):
        logfire.info("开始处理公告数据，共 {count} 只股票", count=len(stock_list))

        # 1. 获取公告数据
        announcements, today = await fetch_announcements_for_stocks(stock_list)
        if not announcements:
            logfire.info("无公告数据，跳过处理")
            return

        # 2. 哈希去重
        deduped = await deduplicate_announcements(announcements)
        if not deduped:
            logfire.info("公告均已存在，跳过处理")
            return

        # 3. 分类并上传文件
        upload_result = await upload_announcement_files(deduped)

        # 4. 创建 Notion 页面
        stock_id_map = {s.code: s.id for s in stock_list}
        success_hashes = await create_announcement_pages(
            upload_result.succeeded, stock_id_map
        )

        # 5. 保存成功的哈希值
        if success_hashes:
            await save_hash(success_hashes)

        # 6. 更新每只股票的最后更新时间
        processed_stocks = {item.announcement.stock for item in deduped}
        for stock_code in processed_stocks:
            await set_update_time(
                stock_code,
                "announcements",
                update_time=convert_datetime_to_notion_date(today),
            )

        logfire.info("公告数据处理完成")


__all__ = ["process_announcements_for_stock_list"]
