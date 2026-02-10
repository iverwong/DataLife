# ruff: noqa: E402

# 加载环境变量
from dotenv import load_dotenv

load_dotenv()


import asyncio
import logging

from core.db import init_db
from core.notion import get_stock_pool

# 初始化日志
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    await init_db()

    stock_list = await get_stock_pool()

    # 处理主营构成数据
    from core.business_data_handler import process_business_data_for_stock_list

    await process_business_data_for_stock_list(stock_list)

    # 处理巨潮公告
    from core.announcements_data_handler import (
        process_announcements_data_for_stock_list,
    )

    await process_announcements_data_for_stock_list(stock_list)


if __name__ == "__main__":
    asyncio.run(main())
