"""
主营业务构成
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
    """
    定义一个命名元组类，用于存储业务数据的相关信息。

    参数:
        report_date (date): 报告日期，表示数据所属的时间点。
        industry_df (DataFrame): 行业相关数据的DataFrame，包含行业维度的业务指标。
        product_df (DataFrame): 产品相关数据的DataFrame，包含产品维度的业务指标。
        region_df (DataFrame): 区域相关数据的DataFrame，包含区域维度的业务指标。
    """

    report_date: date
    industry_df: DataFrame
    product_df: DataFrame
    region_df: DataFrame


async def get_business(stock_code: str) -> BusinessData:
    """
    获取指定股票代码的主营业务构成数据。

    参数:
        stock_code (str): 股票代码，用于标识具体的上市公司。

    返回:
        BusinessData: 包含主营业务构成数据的对象，包括报告日期、分行业数据、分产品数据和分地区数据。
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
