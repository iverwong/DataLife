from core.db import HashContentWithHash


from datetime import datetime

from loguru import logger
from .data import get_business
from .db import check_hash, get_update_time, save_hash, set_update_time
from .models import NotionDate
from .notion import (
    NotionContentBuilder,
    StockPool,
    cover_datetime_to_notion_date,
    create_dataflow_page,
)
from .db import HashContent


async def process_business_data_for_stock_list(stock_list: list[StockPool]) -> None:
    """
    异步处理股票列表中的主营构成数据。

    该函数遍历传入的股票列表，检查每只股票的主营构成数据是否需要更新。如果需要更新，
    则获取最新的主营构成数据，并将其整理成Notion页面格式后创建新的数据流页面。同时，
    更新该股票主营构成数据的最后更新时间。

    参数:
        stock_list (list[StockPool]): 包含股票信息的列表，每个元素是一个StockPool对象，
                                    其中包含股票代码和ID等信息。

    返回值:
        None: 该函数不返回任何值。
    """
    task_logger = logger.bind(stock_list=[stock.code for stock in stock_list])
    task_logger.info("开始处理股票列表中的主营构成数据")
    # 添加主营构成数据
    task_logger.info("开始获取股票列表的主营构成数据更新时间")
    update_times = await get_update_time(
        [stock.code for stock in stock_list], "business"
    )
    task_logger.success(
        "成功获取股票列表的主营构成数据更新时间", update_times=update_times
    )
    for i in range(len(stock_list)):
        stock = stock_list[i].code
        id = stock_list[i].id
        stock_task_logger = task_logger.bind(stock=stock)
        # 如果半年数据还没到下个半年，则跳过更新
        if not _should_update_half_year(update_times[stock]):
            stock_task_logger.info("股票{}主营构成数据已更新，跳过更新", stock)
            continue

        content = NotionContentBuilder()
        business_data = await get_business(stock)

        # 构建去重内容
        hash_content: HashContent = HashContent(
            data_type="business",
            content=f"{stock}-{business_data.report_date}-主营构成",
        )

        # 检查是否已存在
        filtered: list[HashContentWithHash] = await check_hash([hash_content])
        if not filtered:
            stock_task_logger.info("股票{}主营构成数据已存在，跳过创建页面", stock)
            continue

        content = (
            content.add_heading("按行业分类", level=3)
            .add_table_from_dataframe(business_data.industry_df)
            .add_heading("按产品分类", level=3)
            .add_table_from_dataframe(business_data.product_df)
            .add_heading("按地区分类", level=3)
            .add_table_from_dataframe(business_data.region_df)
        )

        notion_logger = stock_task_logger.bind(
            stock=stock, data_type="主营构成", published_date=business_data.report_date
        )
        notion_logger.info("开始创建{}-主营业务构成数据流页面", stock)
        page_result = await create_dataflow_page(
            title=f"{stock}-{business_data.report_date}-主营构成",
            published_date=business_data.report_date,
            source_api=f"{get_business.__module__}.{get_business.__name__}",
            data_type="主营构成",
            relation=id,
            content=content.build(),
        )
        if page_result:
            notion_logger.success("成功创建{}-主营业务构成数据流页面", stock)

            await save_hash([each["hash"] for each in filtered])

            await set_update_time(
                stock,
                "business",
                update_time=cover_datetime_to_notion_date(business_data.report_date),
            )
        else:
            notion_logger.error("创建{}-主营业务构成数据流页面失败", stock)


def _should_update_half_year(last_update_str: NotionDate | None):
    """
    判断是否需要更新半年度数据。

    参数:
        last_update_str (NotionDate | None): 上次更新的日期字符串，格式应为 YYYY-MM-DD。
                                            如果为 None，则表示从未更新过。

    返回:
        bool: 如果需要更新则返回 True，否则返回 False。
    """

    # 如果为空，需要更新
    if not last_update_str:
        return True

    # 只取前10个字符作为日期（YYYY-MM-DD）
    date_str = last_update_str[:10]
    last_update = datetime.strptime(date_str, "%Y-%m-%d")

    year = last_update.year
    month = last_update.month
    day = last_update.day

    # 确定当前是哪个季度末
    if month == 6 and day == 30:  # Q2
        next_query_date = datetime(year + 1, 1, 1)
    elif month == 12 and day == 31:  # Q4
        next_query_date = datetime(year + 1, 7, 1)
    else:
        logger.warning(
            "传入的日期不是季度末，该函数仅能处理季度末数据，考虑排查数据错误"
        )
        return False

    # 获取当前日期
    now = datetime.now()

    # 判断是否已过下一个更新日期
    return now >= next_query_date
