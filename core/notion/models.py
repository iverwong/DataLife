"""
Notion API 端点 Pydantic 模型

覆盖本项目实际调用的以下端点:
- POST /v1/pages                       (pages.create)
- POST /v1/databases/{id}/query        (data_sources.query)
- POST /v1/file_uploads                (file_uploads.create)
- POST /v1/file_uploads/{id}/send      (file_uploads.send)
- GET  /v1/file_uploads/{id}           (file_uploads.retrieve)

参考文档: https://developers.notion.com/reference/intro
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag


# ============================================================
# 共享引用对象
# ============================================================


class EmptyObject(BaseModel):
    pass


class Link(BaseModel):
    """文本内嵌链接"""

    url: str


class ExternalUrl(BaseModel):
    """外部 URL 引用"""

    url: str


class FileUploadReference(BaseModel):
    """通过 file_upload id 引用已上传文件"""

    id: str


class InternalFile(BaseModel):
    """Notion 内部托管文件（响应中返回）"""

    url: str
    expiry_time: str


class FileUploadData(BaseModel):
    """通过 file_upload 上传的文件数据（响应中返回）"""

    id: str
    url: str
    expiry_time: str


# ============================================================
# 共享基础模型
# ============================================================


class PartialUser(BaseModel):
    """Notion 部分用户对象

    https://developers.notion.com/reference/user
    """

    object: Literal["user"] = "user"
    id: str


class TextContent(BaseModel):
    """Rich text 中的纯文本内容"""

    content: str
    link: Link | None = None


class Annotations(BaseModel):
    """Rich text 文本注释（样式）"""

    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    underline: bool = False
    code: bool = False
    color: str = "default"


class RichTextInput(BaseModel):
    """Rich text 输入对象（写入时使用）

    https://developers.notion.com/reference/rich-text
    """

    type: Literal["text"] = "text"
    text: TextContent


class RichTextObject(BaseModel):
    """Rich text 完整对象（API 响应中返回）

    https://developers.notion.com/reference/rich-text
    """

    type: Literal["text", "mention", "equation"] = "text"
    text: TextContent | None = None
    annotations: Annotations | None = None
    plain_text: str | None = None
    href: str | None = None


# ============================================================
# Icon & Cover 模型
# ============================================================


class EmojiIcon(BaseModel):
    """Emoji 图标"""

    type: Literal["emoji"] = "emoji"
    emoji: str


class ExternalIcon(BaseModel):
    """外部图标"""

    type: Literal["external"] = "external"
    external: ExternalUrl


class FileUploadIcon(BaseModel):
    """文件上传图标（请求时使用）"""

    type: Literal["file_upload"] = "file_upload"
    file_upload: FileUploadReference


class FileIcon(BaseModel):
    """Notion 内部文件图标（响应中返回）"""

    type: Literal["file"] = "file"
    file: InternalFile


IconRequest = EmojiIcon | ExternalIcon | FileUploadIcon
IconResponse = EmojiIcon | ExternalIcon | FileIcon


class ExternalCover(BaseModel):
    """外部封面"""

    type: Literal["external"] = "external"
    external: ExternalUrl


class FileUploadCover(BaseModel):
    """文件上传封面（请求时使用）"""

    type: Literal["file_upload"] = "file_upload"
    file_upload: FileUploadReference


class FileCover(BaseModel):
    """Notion 内部文件封面（响应中返回）"""

    type: Literal["file"] = "file"
    file: InternalFile


CoverRequest = ExternalCover | FileUploadCover
CoverResponse = ExternalCover | FileCover


# ============================================================
# Block 模型（用于 children / content）
# ============================================================


class DividerContent(BaseModel):
    """Divider block 内容（空对象）"""


class RichTextBlockContent(BaseModel):
    """富文本 block 内容（段落、标题共享）"""

    rich_text: list[RichTextInput]


class CalloutContent(BaseModel):
    """Callout block 内容"""

    rich_text: list[RichTextInput]
    icon: EmojiIcon | ExternalIcon


class TableRowContent(BaseModel):
    """表格行内容"""

    cells: list[list[RichTextInput]]


class TableRowBlock(BaseModel):
    """表格行 block"""

    type: Literal["table_row"] = "table_row"
    table_row: TableRowContent


class TableContent(BaseModel):
    """表格 block 内容"""

    table_width: int
    has_column_header: bool = True
    has_row_header: bool = False
    children: list[TableRowBlock]


class ParagraphBlock(BaseModel):
    """段落 block"""

    object: Literal["block"] = "block"
    type: Literal["paragraph"] = "paragraph"
    paragraph: RichTextBlockContent


class Heading1Block(BaseModel):
    """一级标题 block"""

    object: Literal["block"] = "block"
    type: Literal["heading_1"] = "heading_1"
    heading_1: RichTextBlockContent


class Heading2Block(BaseModel):
    """二级标题 block"""

    object: Literal["block"] = "block"
    type: Literal["heading_2"] = "heading_2"
    heading_2: RichTextBlockContent


class Heading3Block(BaseModel):
    """三级标题 block"""

    object: Literal["block"] = "block"
    type: Literal["heading_3"] = "heading_3"
    heading_3: RichTextBlockContent


class DividerBlock(BaseModel):
    """分隔线 block"""

    object: Literal["block"] = "block"
    type: Literal["divider"] = "divider"
    divider: DividerContent


class CalloutBlock(BaseModel):
    """Callout block"""

    object: Literal["block"] = "block"
    type: Literal["callout"] = "callout"
    callout: CalloutContent


class TableBlock(BaseModel):
    """表格 block"""

    object: Literal["block"] = "block"
    type: Literal["table"] = "table"
    table: TableContent


Block = (
    ParagraphBlock
    | Heading1Block
    | Heading2Block
    | Heading3Block
    | DividerBlock
    | CalloutBlock
    | TableBlock
)


# ============================================================
# 属性值模型 — 请求（写入）
# ============================================================


class DateValue(BaseModel):
    """日期值"""

    start: str
    end: str | None = None
    time_zone: str | None = None


class SelectOption(BaseModel):
    """选项对象（id 与 name 至少提供一个）"""

    id: str | None = None
    name: str | None = None


class RelationItem(BaseModel):
    """关联条目"""

    id: str


class FileItemUpload(BaseModel):
    """文件条目 — file_upload 模式"""

    file_upload: FileUploadReference


class FileItemExternal(BaseModel):
    """文件条目 — external 模式"""

    name: str
    external: ExternalUrl


class TitlePropertyRequest(BaseModel):
    """标题属性 — 请求

    示例: ``{"title": [{"text": {"content": "..."}}]}``
    """

    title: list[RichTextInput]


class RichTextPropertyRequest(BaseModel):
    """富文本属性 — 请求

    示例: ``{"rich_text": [{"text": {"content": "..."}}]}``
    """

    rich_text: list[RichTextInput]


class DatePropertyRequest(BaseModel):
    """日期属性 — 请求

    示例: ``{"date": {"start": "2024-01-01"}}``
    """

    date: DateValue


class SelectPropertyRequest(BaseModel):
    """单选属性 — 请求

    示例: ``{"select": {"id": "abc"}}``
    """

    select: SelectOption


class RelationPropertyRequest(BaseModel):
    """关联属性 — 请求

    示例: ``{"relation": [{"id": "..."}]}``
    """

    relation: list[RelationItem]


class UrlPropertyRequest(BaseModel):
    """URL 属性 — 请求

    示例: ``{"url": "https://..."}``
    """

    url: str


class FilesPropertyRequest(BaseModel):
    """文件属性 — 请求

    示例: ``{"files": [{"file_upload": {"id": "..."}}]}``
    """

    files: list[FileItemUpload | FileItemExternal]


PropertyValueRequest = (
    TitlePropertyRequest
    | RichTextPropertyRequest
    | DatePropertyRequest
    | SelectPropertyRequest
    | RelationPropertyRequest
    | UrlPropertyRequest
    | FilesPropertyRequest
)


# ============================================================
# 属性值模型 — 响应（读取）
# ============================================================


# 文件属性响应条目


class FileResponseInternal(BaseModel):
    """文件属性响应条目 — Notion 内部文件"""

    name: str
    type: Literal["file"] = "file"
    file: InternalFile


class FileResponseExternal(BaseModel):
    """文件属性响应条目 — 外部文件"""

    name: str
    type: Literal["external"] = "external"
    external: ExternalUrl


class FileResponseUpload(BaseModel):
    """文件属性响应条目 — file_upload"""

    name: str
    type: Literal["file_upload"] = "file_upload"
    file_upload: FileUploadData


FileResponseItem = FileResponseInternal | FileResponseExternal | FileResponseUpload


# 属性响应模型


class TitlePropertyResponse(BaseModel):
    """标题属性 — 响应"""

    id: str
    type: Literal["title"] = "title"
    title: list[RichTextObject]


class RichTextPropertyResponse(BaseModel):
    """富文本属性 — 响应"""

    id: str
    type: Literal["rich_text"] = "rich_text"
    rich_text: list[RichTextObject]


class DatePropertyResponse(BaseModel):
    """日期属性 — 响应"""

    id: str
    type: Literal["date"] = "date"
    date: DateValue | None = None


class SelectPropertyResponse(BaseModel):
    """单选属性 — 响应"""

    id: str
    type: Literal["select"] = "select"
    select: SelectOption | None = None


class RelationPropertyResponse(BaseModel):
    """关联属性 — 响应"""

    id: str
    type: Literal["relation"] = "relation"
    relation: list[RelationItem]
    has_more: bool = False


class UrlPropertyResponse(BaseModel):
    """URL 属性 — 响应"""

    id: str
    type: Literal["url"] = "url"
    url: str | None = None


class FilesPropertyResponse(BaseModel):
    """文件属性 — 响应"""

    id: str
    type: Literal["files"] = "files"
    files: list[FileResponseItem]


class CheckboxPropertyResponse(BaseModel):
    """复选框属性 — 响应"""

    id: str
    type: Literal["checkbox"] = "checkbox"
    checkbox: bool


class NumberPropertyResponse(BaseModel):
    """数字属性 — 响应"""

    id: str
    type: Literal["number"] = "number"
    number: float | int | None = None


class GenericPropertyResponse(BaseModel):
    """通用属性响应 — 未明确建模的属性类型回退"""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")
    id: str
    type: str


_KNOWN_PROPERTY_TYPES = frozenset(
    {
        "title",
        "rich_text",
        "date",
        "select",
        "relation",
        "url",
        "files",
        "checkbox",
        "number",
    }
)


def _resolve_property_type(v: dict[str, object] | BaseModel) -> str:
    """根据 type 字段分发到对应的属性响应模型"""
    if isinstance(v, dict):
        t = v.get("type", "")
    else:
        t = getattr(v, "type", "")
    return str(t) if t in _KNOWN_PROPERTY_TYPES else "_generic"


PropertyValueResponse = Annotated[
    (
        Annotated[TitlePropertyResponse, Tag("title")]
        | Annotated[RichTextPropertyResponse, Tag("rich_text")]
        | Annotated[DatePropertyResponse, Tag("date")]
        | Annotated[SelectPropertyResponse, Tag("select")]
        | Annotated[RelationPropertyResponse, Tag("relation")]
        | Annotated[UrlPropertyResponse, Tag("url")]
        | Annotated[FilesPropertyResponse, Tag("files")]
        | Annotated[CheckboxPropertyResponse, Tag("checkbox")]
        | Annotated[NumberPropertyResponse, Tag("number")]
        | Annotated[GenericPropertyResponse, Tag("_generic")]
    ),
    Discriminator(_resolve_property_type),
]


# ============================================================
# Parent 模型
# ============================================================


class DataSourceParent(BaseModel):
    """数据源父级"""

    data_source_id: str


class DatabaseParent(BaseModel):
    """数据库父级"""

    database_id: str


class PageParent(BaseModel):
    """页面父级"""

    page_id: str


class WorkspaceParent(BaseModel):
    """工作区父级"""

    workspace: Literal[True] = True


class ParentResponse(BaseModel):
    """响应中的 parent 对象"""

    type: Literal["data_source_id", "database_id", "page_id", "workspace"]
    data_source_id: str | None = None
    database_id: str | None = None
    page_id: str | None = None
    workspace: bool | None = None


# ============================================================
# pages.create — 创建页面
# https://developers.notion.com/reference/post-page
# ============================================================


class CreatePageRequest(BaseModel):
    """POST /v1/pages 请求体"""

    parent: DataSourceParent | DatabaseParent | PageParent | WorkspaceParent
    properties: dict[str, PropertyValueRequest]
    children: list[Block] | None = None
    icon: IconRequest | None = None
    cover: CoverRequest | None = None


class PageResponse(BaseModel):
    """POST /v1/pages 响应体 (Page Object)

    https://developers.notion.com/reference/page
    """

    object: Literal["page"] = "page"
    id: str
    created_time: str
    last_edited_time: str
    created_by: PartialUser
    last_edited_by: PartialUser
    archived: bool = False
    in_trash: bool = False
    url: str
    public_url: str | None = None
    parent: ParentResponse
    properties: dict[str, PropertyValueResponse]
    icon: IconResponse | None = None
    cover: CoverResponse | None = None


# ============================================================
# data_sources.query — 查询数据源
# https://developers.notion.com/reference/post-database-query
# ============================================================


# Filter 模型

FilterConditionValue = str | int | float | bool | None


class PropertyFilter(BaseModel):
    """属性过滤条件

    示例: ``{"property": "Name", "rich_text": {"contains": "test"}}``
    """

    property: str
    rich_text: dict[str, FilterConditionValue] | None = None
    number: dict[str, FilterConditionValue] | None = None
    checkbox: dict[str, FilterConditionValue] | None = None
    select: dict[str, FilterConditionValue] | None = None
    multi_select: dict[str, FilterConditionValue] | None = None
    date: dict[str, FilterConditionValue] | None = None
    people: dict[str, FilterConditionValue] | None = None
    files: dict[str, FilterConditionValue] | None = None
    relation: dict[str, FilterConditionValue] | None = None
    formula: dict[str, FilterConditionValue] | None = None
    rollup: dict[str, FilterConditionValue] | None = None
    status: dict[str, FilterConditionValue] | None = None
    unique_id: dict[str, FilterConditionValue] | None = None


class TimestampFilter(BaseModel):
    """时间戳过滤条件

    示例: ``{"timestamp": "created_time", "created_time": {"after": "2024-01-01"}}``
    """

    timestamp: Literal["created_time", "last_edited_time"]
    created_time: dict[str, FilterConditionValue] | None = None
    last_edited_time: dict[str, FilterConditionValue] | None = None


class CompoundFilter(BaseModel):
    """复合过滤条件（and / or）"""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    and_: list[Filter] | None = Field(default=None, alias="and")
    or_: list[Filter] | None = Field(default=None, alias="or")


Filter = PropertyFilter | TimestampFilter | CompoundFilter

# 解析 CompoundFilter 中的 Filter 前向引用
_ = CompoundFilter.model_rebuild()


class SortCriterion(BaseModel):
    """排序条件"""

    property: str | None = None
    timestamp: Literal["created_time", "last_edited_time"] | None = None
    direction: Literal["ascending", "descending"] = "ascending"


class QueryDataSourceRequest(BaseModel):
    """POST /v1/databases/{database_id}/query 请求体"""

    filter: Filter | None = None
    sorts: list[SortCriterion] | None = None
    start_cursor: str | None = None
    page_size: int | None = Field(default=None, ge=1, le=100)


class QueryDataSourceResponse(BaseModel):
    """POST /v1/databases/{database_id}/query 响应体

    https://developers.notion.com/reference/post-database-query
    """

    object: Literal["list"] = "list"
    results: list[PageResponse]
    has_more: bool
    next_cursor: str | None = None
    type: str = "page_or_database"


# ============================================================
# file_uploads.create — 创建文件上传
# https://developers.notion.com/reference/create-a-file-upload
# ============================================================


class CreateFileUploadLocalRequest(BaseModel):
    """POST /v1/file_uploads 请求体 — 本地单次上传模式

    用于上传本地文件，创建后通过 send 端点发送文件内容。
    """

    mode: Literal["single_part"] = "single_part"
    filename: str
    content_type: str | None = None


class CreateFileUploadMultiPartRequest(BaseModel):
    """POST /v1/file_uploads 请求体 — 本地多次上传模式

    用于大文件分片上传。
    """

    mode: Literal["multi_part"] = "multi_part"
    filename: str
    content_type: str | None = None
    number_of_parts: int = Field(ge=1, le=10000)


class CreateFileUploadExternalRequest(BaseModel):
    """POST /v1/file_uploads 请求体 — 外部 URL 模式

    Notion 服务端从给定 URL 拉取文件。
    """

    mode: Literal["external_url"] = "external_url"
    filename: str
    external_url: str


# ============================================================
# file_uploads.send — 发送文件内容
# https://developers.notion.com/guides/data-apis/uploading-small-files
# ============================================================
# 注: send 端点使用 multipart/form-data 发送二进制文件，
#     路径参数为 file_upload_id，无 JSON 请求体。
#     此处仅建模路径参数，实际文件内容通过 SDK file 参数传递。


class SendFileUploadParams(BaseModel):
    """POST /v1/file_uploads/{file_upload_id}/send 路径参数"""

    file_upload_id: str


# ============================================================
# file_uploads.retrieve — 查询文件上传状态
# https://developers.notion.com/reference/retrieve-a-file-upload
# ============================================================
# 注: retrieve 端点为 GET 请求，路径参数为 file_upload_id，无请求体。


class RetrieveFileUploadParams(BaseModel):
    """GET /v1/file_uploads/{file_upload_id} 路径参数"""

    file_upload_id: str


# ============================================================
# file_uploads 共享响应模型
# (create / send / retrieve 三个端点返回相同结构)
# ============================================================


class FileImportResultError(BaseModel):
    """文件导入结果错误"""

    type: Literal[
        "validation_error", "internal_system_error", "download_error", "upload_error"
    ]
    code: str
    message: str
    parameter: str | None
    status_code: int | None


class FileImportError(BaseModel):
    """文件导入错误详情"""

    imported_time: datetime
    type: Literal["error"]
    error: FileImportResultError


class FileImportSuccess(BaseModel):
    """文件导入成功详情"""

    imported_time: datetime
    type: Literal["success"]
    success: EmptyObject


FileImportResult = Annotated[
    (
        Annotated[FileImportSuccess, Tag("success")]
        | Annotated[FileImportError, Tag("error")]
    ),
    Discriminator("type"),
]


class NumberOfParts(BaseModel):
    """文件分片计数"""

    total: int = Field(ge=0)
    sent: int = Field(ge=0)


class FileUploadResponse(BaseModel):
    """文件上传对象 — create / send / retrieve 共享响应

    https://developers.notion.com/reference/create-a-file-upload
    https://developers.notion.com/reference/retrieve-a-file-upload
    """

    object: Literal["file_upload"] = "file_upload"
    id: str
    created_time: str
    created_by: PartialUser | None = None
    last_edited_time: str | None = None
    archived: bool = False
    expiry_time: str | None = None
    status: Literal["pending", "uploading", "uploaded", "expired", "failed"]
    filename: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    upload_url: str | None = None
    complete_url: str | None = None
    file_import_result: FileImportResult | None = None
    number_of_parts: NumberOfParts | None = None
