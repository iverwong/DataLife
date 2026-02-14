"""
资讯流数据库的相关操作
"""

import os
from datetime import date, datetime
from typing import Literal

from loguru import logger

from .client import notion
from .datetime_helper import cover_datetime_to_notion_date
from .models import (
    Block,
    CreatePageRequest,
    DataSourceParent,
    DatePropertyRequest,
    DateValue,
    FileItemUpload,
    FileUploadReference,
    FilesPropertyRequest,
    PropertyValueRequest,
    RelationItem,
    RelationPropertyRequest,
    RichTextInput,
    RichTextPropertyRequest,
    SelectOption,
    SelectPropertyRequest,
    TextContent,
    TitlePropertyRequest,
    UrlPropertyRequest,
)
from .retry_helper import with_retry

TYPE_MAPPING = {
    "新闻资讯": "zUJ`",
    "公告披露": "{NTW",
    "财务数据": "LWAO",
    "研究报告": "OV~n",
    "主营构成": "NqbV",
}

FLOW_DATABASE = os.getenv("FLOW_DATABASE")


DataType = Literal["新闻资讯", "公告披露", "财务数据", "研究报告", "主营构成"]


@with_retry()
async def create_dataflow_page(
    title: str,
    published_date: datetime | date,
    source_api: str,
    data_type: DataType,
    relation: str,
    attachment_id: str | None = None,
    source_url: str | None = None,
    content: list[Block] | None = None,
) -> bool:
    """在资讯流数据库中创建一个页面

    Args:
        title: 标题
        published_date: 发布时间
        source_api: 来源接口
        data_type: 数据类型
        relation: 关联股票
        attachment_id: 附件 file_upload ID
        source_url: 原文链接
        content: 正文内容（Block 列表）

    Returns:
        创建成功返回 True，失败返回 False
    """
    properties: dict[str, PropertyValueRequest] = {
        "标题": TitlePropertyRequest(
            title=[RichTextInput(text=TextContent(content=title))]
        ),
        "发布时间": DatePropertyRequest(
            date=DateValue(start=cover_datetime_to_notion_date(published_date))
        ),
        "来源接口": RichTextPropertyRequest(
            rich_text=[RichTextInput(text=TextContent(content=source_api))]
        ),
        "数据类型": SelectPropertyRequest(
            select=SelectOption(id=TYPE_MAPPING[data_type])
        ),
        "关联股票": RelationPropertyRequest(relation=[RelationItem(id=relation)]),
    }
    if source_url:
        properties["原文链接"] = UrlPropertyRequest(url=source_url)
    if attachment_id:
        properties["附件"] = FilesPropertyRequest(
            files=[FileItemUpload(file_upload=FileUploadReference(id=attachment_id))]
        )
    notion_logger = logger.bind(
        parent_id=FLOW_DATABASE, title=title, data_type=data_type
    )
    try:
        request = CreatePageRequest(
            parent=DataSourceParent(data_source_id=FLOW_DATABASE or ""),
            properties=properties,
            children=content,
        )

        notion_logger.info("开始在Notion中创建页面")
        await notion.pages.create(**request.model_dump(exclude_none=True))
        notion_logger.success("成功在Notion中创建页面")
        return True
    except Exception:
        notion_logger.exception("创建页面失败")
        return False
