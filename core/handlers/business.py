"""主营构成数据处理编排模块。

协调 AkShare 数据采集、去重和 Notion 页面创建的完整流程。
"""

from datetime import datetime

from loguru import logger

from core.data import get_business
from core.db import HashContent, HashContentWithHash, check_hash, get_update_time, save_hash, set_update_time
from core.models import NotionDate
from core.notion import (
    NotionContentBuilder,
    StockPool,
    convert_datetime_to_notion_date,
    create_dataflow_page,
)


async def process_business_data_for_stock_list(stock_list: list[StockPool]) -> None:
    """处理股票列表中的主营构成数据。

    遍历股票列表，检查每只股票是否需要更新主营构成数据。需要更新时，
    获取最新数据、构建 Notion 页面内容并创建数据流页面。

    Args:
        stock_list: 待处理的股票列表。
    """
    task_logger = logger.bind(stock_list=[stock.code for stock in stock_list])
    task_logger.info("开始处理股票列表中的主营构成数据")

    update_times = await get_update_time(
        [stock.code for stock in stock_list], "business"
    )
    task_logger.success(
        "成功获取股票列表的主营构成数据更新时间", update_times=update_times
    )

    for stock_pool in stock_list:
        stock_code = stock_pool.code
        stock_id = stock_pool.id
        stock_task_logger = task_logger.bind(stock=stock_code)

        # 如果半年数据还没到下个半年，则跳过更新
        if not _should_update_half_year(update_times[stock_code]):
            stock_task_logger.info("股票{}主营构成数据已更新，跳过更新", stock_code)
            continue

        try:
            business_data = await get_business(stock_code)
        except Exception:
            stock_task_logger.exception("获取股票{}主营构成数据失败，跳过", stock_code)
            continue

        # 构建去重内容
        hash_content = HashContent(
            data_type="business",
            content=f"{stock_code}-{business_data.report_date}-主营构成",
        )

        # 检查是否已存在
        filtered: list[HashContentWithHash] = await check_hash([hash_content])
        if not filtered:
            stock_task_logger.info("股票{}主营构成数据已存在，跳过创建页面", stock_code)
            continue

        # 构建页面内容
        content = (
            NotionContentBuilder()
            .add_heading("按行业分类", level=3)
            .add_table_from_dataframe(business_data.industry_df)
            .add_heading("按产品分类", level=3)
            .add_table_from_dataframe(business_data.product_df)
            .add_heading("按地区分类", level=3)
            .add_table_from_dataframe(business_data.region_df)
        )

        notion_logger = stock_task_logger.bind(
            data_type="主营构成", published_date=business_data.report_date
        )
        notion_logger.info("开始创建{}-主营业务构成数据流页面", stock_code)

        page_result = await create_dataflow_page(
            title=f"{stock_code}-{business_data.report_date}-主营构成",
            published_date=business_data.report_date,
            source_api=f"{get_business.__module__}.{get_business.__name__}",
            data_type="主营构成",
            relation=stock_id,
            content=content.build(),
        )

        if page_result:
            notion_logger.success("成功创建{}-主营业务构成数据流页面", stock_code)
            await save_hash([each.hash_value for each in filtered])
            await set_update_time(
                stock_code,
                "business",
                update_time=convert_datetime_to_notion_date(business_data.report_date),
            )
        else:
            notion_logger.error("创建{}-主营业务构成数据流页面失败", stock_code)


def _should_update_half_year(last_update_str: NotionDate | None) -> bool:
    """判断是否需要更新半年度数据。

    基于报告日期所在的半年度确定下次查询时间：
    - Q2（6月30日）-> 次年1月1日查询
    - Q4（12月31日）-> 次年7月1日查询

    Args:
        last_update_str: 上次更新的 Notion 日期字符串（YYYY-MM-DD 格式），
                         None 表示从未更新过。

    Returns:
        True 表示需要更新，False 表示无需更新。
    """
    if not last_update_str:
        return True

    date_str = last_update_str[:10]
    last_update = datetime.strptime(date_str, "%Y-%m-%d")

    year = last_update.year
    month = last_update.month
    day = last_update.day

    if month == 6 and day == 30:  # Q2
        next_query_date = datetime(year + 1, 1, 1)
    elif month == 12 and day == 31:  # Q4
        next_query_date = datetime(year + 1, 7, 1)
    else:
        logger.warning(
            "传入的日期{}不是季度末，该函数仅能处理季度末数据，考虑排查数据错误",
            last_update_str,
        )
        return False

    now = datetime.now()
    return now >= next_query_date
