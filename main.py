# ruff: noqa: E402

# 配置日志
from core.logs import setup_logging

setup_logging()

import logfire

# 加载环境变量
logfire.info("程序启动，加载环境变量")

from dotenv import load_dotenv

_ = load_dotenv()


import asyncio

from core.db import dispose_engine, init_db
from core.notion import get_stock_pool


async def main() -> None:
    try:
        with logfire.span("main_sync_job"):
            await init_db()

            stock_list = await get_stock_pool()

            # 处理主营构成数据
            from core.handlers.business import process_business_data_for_stock_list

            await process_business_data_for_stock_list(stock_list)

            # 处理巨潮公告
            from core.handlers.announcements import process_announcements_for_stock_list

            await process_announcements_for_stock_list(stock_list)
    finally:
        from core.notion.client import close_client

        await close_client()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
