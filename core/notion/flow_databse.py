"""
资讯流数据库的相关操作
"""

import logging
import os
from datetime import date, datetime
from typing import Literal

from . import notion
from .datetime_helper import cover_datetime_to_notion_date

logger = logging.getLogger(__name__)

TYPE_MAPPING = {
    "新闻资讯": "zUJ`",
    "公告披露": "{NTW",
    "财务数据": "LWAO",
    "研究报告": "OV~n",
    "主营构成": "NqbV",
}

FLOW_DATABASE = os.getenv("FLOW_DATABASE")


DataType = Literal["新闻资讯", "公告披露", "财务数据", "研究报告", "主营构成"]


async def create_dataflow_page(
    title: str,
    published_date: datetime | date,
    source_api: str,
    data_type: DataType,
    relation: str,
    attachment_id: str | None = None,
    source_url: str | None = None,
    content: list[dict] | None = None,
) -> bool:
    logger.debug(
        f"创建页面：入参：{title}, {published_date}, {source_api}, {data_type}, {relation}, {attachment_id}, {source_url}, {content}"
    )
    """在资讯流数据库中创建一个页面
    :param title: 标题
    :param published_date: 发布时间
    :param source_api: 来源接口
    :param data_type: 数据类型
    :param relation: 关联股票
    :param attachment_url: 附件链接
    :param source_url: 原文链接
    :param content: 正文内容
    :return: 创建成功返回 True，失败返回 False
    """
    properties = {
        "标题": {"title": [{"text": {"content": title}}]},
        "发布时间": {"date": {"start": cover_datetime_to_notion_date(published_date)}},
        "来源接口": {"rich_text": [{"text": {"content": source_api}}]},
        "数据类型": {"select": {"id": TYPE_MAPPING[data_type]}},
        "关联股票": {"relation": [{"id": relation}]},
    }
    if source_url:
        properties["原文链接"] = {"url": source_url}
    if attachment_id:
        properties["附件"] = {"files": [{"file_upload": {"id": attachment_id}}]}
    try:
        # 构建 create 参数，只在 content 不为 None 时传递 children
        create_params = {
            "parent": {"data_source_id": FLOW_DATABASE},
            "properties": properties,
        }
        if content is not None:
            create_params["children"] = content

        await notion.pages.create(**create_params)
        return True
    except Exception as e:
        logger.error(f"创建页面失败: 标题={title}, 错误={e}")
        return False
