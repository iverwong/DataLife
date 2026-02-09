import datetime
import logging
from datetime import date, datetime
from functools import lru_cache
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)


class Announcement(NamedTuple):
    """
    表示一个公告信息的命名元组类。

    该类用于存储与公告相关的基本信息，包括公告的唯一标识、所属股票、标题、
    文件大小、下载链接以及发布时间等字段。

    属性:
        id (str): 巨潮资讯网公告的唯一标识符。
        stock (str): 公告所属的股票代码或名称。
        title (str): 公告的标题。
        size (int): 公告文件的大小（KB）。
        url (str): 公告文件的下载链接。
        published_date (datetime): 公告的发布日期和时间。
    """

    id: str
    stock: str
    title: str
    size: int
    url: str
    published_date: datetime


async def get_announcements(
    stock_list: list[str],
    start_date: date,
    end_date: date,
) -> list[Announcement]:
    """
    获取指定股票列表在给定日期范围内的公告信息。

    参数:
        stock_list (list[str]): 股票代码列表，用于查询相关公告。
        start_date (date): 查询公告的起始日期。
        end_date (date): 查询公告的结束日期。

    返回:
        list[Announcement]: 包含公告信息的列表，每个元素为Announcement对象，
                            包括公告ID、股票代码、标题、文件大小、下载链接和发布时间等信息。
    """
    if len(stock_list) == 0:
        return []
    logger.info("获取公告信息")

    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

    stock_item = ";".join(
        [f"{stock},{(await _get_stock_json())[stock]}" for stock in stock_list]
    )
    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock_item,
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start_date}~{end_date}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(url, params=payload)
        response = res.json()

        announcements = [*response["announcements"]]

        # 使用接口返回的totalpages参数获取**剩余**页数
        page_count = response["totalpages"]

        for i in range(page_count):
            payload["pageNum"] = str(i + 2)
            res = await client.post(url, params=payload)
            response = res.json()
            announcements.extend(response["announcements"])

    # 将report中的摘要、英文版、图文版之类的筛选掉
    announcements = [
        each
        for each in announcements
        if each["announcementTitle"] not in ["摘要", "英文版", "图文版"]
    ]

    result = [
        Announcement(
            each["announcementId"],
            each["secCode"],
            f"{each['secName']}({each['secCode']})-{each['announcementTitle']}",
            each["adjunctSize"],
            f"https://static.cninfo.com.cn/{each['adjunctUrl']}",
            datetime.fromtimestamp(each["announcementTime"] / 1000),
        )
        for each in announcements
    ]
    return result


@lru_cache()
async def _get_stock_json(symbol: str = "沪深京") -> dict:
    """
    获取指定股票类型的JSON数据并解析为字典格式。

    参数:
        symbol (str): 股票类型，默认为"沪深京"。目前仅支持"沪深京"类型。

    返回:
        dict: 以股票代码为键、机构ID为值的字典。

    异常:
        ValueError: 当传入不支持的股票类型时抛出。
    """
    if symbol == "沪深京":
        url = "http://www.cninfo.com.cn/new/data/szse_stock.json"
    # 港股暂不考虑实现
    # elif symbol == "港股":
    #     url = "http://www.cninfo.com.cn/new/data/hke_stock.json"
    else:
        raise ValueError("不受支持的股票类型！")
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    text_json = response.json()
    stock_list = text_json["stockList"]
    return {stock["code"]: stock["orgId"] for stock in stock_list}
