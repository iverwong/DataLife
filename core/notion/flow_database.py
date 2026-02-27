"""资讯流数据库操作模块。

提供在 Notion 资讯流数据库中创建数据流页面的功能，
支持多种属性（标题、日期、类型、关联、附件等）和正文内容块。
"""

import os
from datetime import date, datetime
from typing import Literal

import logfire

from .client import notion
from .datetime_helper import convert_datetime_to_notion_date
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
if not FLOW_DATABASE:
    logfire.warn("环境变量 FLOW_DATABASE 未配置，资讯流数据库操作将失败")


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
            date=DateValue(start=convert_datetime_to_notion_date(published_date))
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
    try:
        request = CreatePageRequest(
            parent=DataSourceParent(data_source_id=FLOW_DATABASE or ""),
            properties=properties,
            children=content,
        )

        logfire.debug("创建 Notion 页面: {title}", title=title)
        await notion.pages.create(**request.model_dump(exclude_none=True))
        logfire.info("页面创建成功: {title}", title=title)
        return True
    except Exception:
        logfire.exception("页面创建失败: {title}", title=title)
        return False
