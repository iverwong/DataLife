"""AkShare 主营业务构成数据采集模块。

从东方财富 AkShare 接口获取上市公司主营构成数据（分行业、分产品、分地区）。
"""

import asyncio
from dataclasses import dataclass
from datetime import date

import akshare as ak  # pyright: ignore[reportMissingTypeStubs]
from loguru import logger
from pandas import DataFrame

_BUSINESS_COLUMNS = [
    "主营构成",
    "主营收入",
    "收入比例",
    "主营成本",
    "成本比例",
    "主营利润",
    "利润比例",
    "毛利率",
]


@dataclass(frozen=True)
class BusinessData:
    """主营业务构成数据。

    Attributes:
        report_date: 报告日期。
        industry_df: 按行业分类的数据。
        product_df: 按产品分类的数据。
        region_df: 按地区分类的数据。
    """

    report_date: date
    industry_df: DataFrame
    product_df: DataFrame
    region_df: DataFrame


async def get_business(stock_code: str) -> BusinessData:
    """获取指定股票的主营业务构成数据。

    根据股票代码判断市场（0/3 开头为深市，否则为沪市），
    调用 AkShare 接口获取最新报告期的分行业、分产品、分地区数据。

    Args:
        stock_code: 六位股票代码。

    Returns:
        包含最新报告期主营构成数据的 BusinessData 对象。
    """
    stock_logger = logger.bind(stock_code=stock_code)
    # 根据股票代码确定请求参数
    code = (
        f"SZ{stock_code}"
        if stock_code[0] == "0" or stock_code[0] == "3"
        else f"SH{stock_code}"
    )
    stock_logger.info("获取股票{}的主营业务构成数据", stock_code)
    raw: object = await asyncio.to_thread(ak.stock_zygc_em, code)
    df = DataFrame(raw)
    stock_logger.success("获取股票{}的主营业务构成数据成功", stock_code)
    report_date: date = df["报告日期"].max()  # pyright: ignore[reportAny]
    # 分行业
    industry_df: DataFrame = (
        df.loc[
            (df["报告日期"] == report_date) & (df["分类类型"].isna()),
            _BUSINESS_COLUMNS,
        ]
        .rename(columns={"主营构成": "行业分类"})
        .reset_index(drop=True)
    )
    # 分产品
    product_df: DataFrame = (
        df.loc[
            (df["报告日期"] == report_date) & (df["分类类型"] == "按产品分类"),
            _BUSINESS_COLUMNS,
        ]
        .rename(columns={"主营构成": "产品分类"})
        .reset_index(drop=True)
    )
    # 分地区
    region_df: DataFrame = (
        df.loc[
            (df["报告日期"] == report_date) & (df["分类类型"] == "按地区分类"),
            _BUSINESS_COLUMNS,
        ]
        .rename(columns={"主营构成": "地区分类"})
        .reset_index(drop=True)
    )

    return BusinessData(report_date, industry_df, product_df, region_df)
