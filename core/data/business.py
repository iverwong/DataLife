"""
主营业务构成
"""

import asyncio
import logging
from datetime import date
from typing import NamedTuple

import akshare as ak
from pandas import DataFrame

logger = logging.getLogger(__name__)


class BusinessData(NamedTuple):
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
    logger.info(f"获取股票{stock_code}的主营业务构成数据")
    # 根据股票代码确定请求参数
    code = (
        f"SZ{stock_code}"
        if stock_code[0] == "0" or stock_code[0] == "3"
        else f"SH{stock_code}"
    )
    df = await asyncio.to_thread(ak.stock_zygc_em, code)
    report_date = df["报告日期"].max()
    # 分行业
    industry_df = df.loc[
        (df["报告日期"] == report_date) & (df["分类类型"].isna()),
        [
            "主营构成",
            "主营收入",
            "收入比例",
            "主营成本",
            "成本比例",
            "主营利润",
            "利润比例",
            "毛利率",
        ],
    ].rename(columns={"主营构成": "行业分类"})
    # 分产品
    product_df = df.loc[
        (df["报告日期"] == report_date) & (df["分类类型"] == "按产品分类"),
        [
            "主营构成",
            "主营收入",
            "收入比例",
            "主营成本",
            "成本比例",
            "主营利润",
            "利润比例",
            "毛利率",
        ],
    ].rename(columns={"主营构成": "产品分类"})
    # 分地区
    region_df = df.loc[
        (df["报告日期"] == report_date) & (df["分类类型"] == "按地区分类"),
        [
            "主营构成",
            "主营收入",
            "收入比例",
            "主营成本",
            "成本比例",
            "主营利润",
            "利润比例",
            "毛利率",
        ],
    ].rename(columns={"主营构成": "地区分类"})

    return BusinessData(report_date, industry_df, product_df, region_df)
