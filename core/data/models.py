"""
外部数据源 API 响应 Pydantic 模型

覆盖本项目实际调用的以下端点:
- POST http://www.cninfo.com.cn/new/hisAnnouncement/query  (公告查询)
- GET  http://www.cninfo.com.cn/new/data/szse_stock.json   (股票代码映射)

AkShare 返回 pandas DataFrame，不在此建模。

参考来源: 巨潮资讯网 http://www.cninfo.com.cn
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# 巨潮资讯网 — 股票代码映射
# GET http://www.cninfo.com.cn/new/data/szse_stock.json
# ============================================================


class StockItem(BaseModel):
    """股票列表中的单只股票条目

    仅建模项目实际使用的字段，其余字段通过 extra="ignore" 忽略。
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    code: str
    orgId: str


class StockListResponse(BaseModel):
    """股票代码映射 API 响应

    GET http://www.cninfo.com.cn/new/data/szse_stock.json
    """

    stockList: list[StockItem]


# ============================================================
# 巨潮资讯网 — 公告查询
# POST http://www.cninfo.com.cn/new/hisAnnouncement/query
# ============================================================


class AnnouncementItem(BaseModel):
    """公告查询结果中的单条公告

    字段说明:
        secCode: 股票代码
        secName: 股票简称
        orgId: 机构 ID
        announcementId: 公告唯一标识
        announcementTitle: 公告标题
        announcementTime: 公告时间（毫秒时间戳）
        adjunctUrl: 附件相对路径
        adjunctSize: 附件大小（KB）
        adjunctType: 附件类型（如 "PDF"）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    secCode: str
    secName: str
    orgId: str
    announcementId: str
    announcementTitle: str
    announcementTime: int
    adjunctUrl: str
    adjunctSize: int
    adjunctType: str | None = None
    storageTime: str | None = None
    columnId: str | None = None
    pageColumn: str | None = None
    announcementType: str | None = None
    associateAnnouncement: str | None = None
    important: bool | None = None
    batchNum: str | None = None
    announcementContent: str = ""
    orgName: str | None = None
    tileSecName: str | None = None
    shortTitle: str | None = None
    announcementTypeName: str | None = None
    secNameList: list[dict[str, str]] | None = None


class AnnouncementsResponse(BaseModel):
    """公告查询 API 响应

    POST http://www.cninfo.com.cn/new/hisAnnouncement/query
    """

    classifiedAnnouncements: object | None = Field(default=None)
    totalSecurities: int = 0
    totalAnnouncement: int = 0
    totalRecordNum: int = 0
    announcements: list[AnnouncementItem] | None = None
    categoryList: list[object] | None = None
    hasMore: bool = False
    totalpages: int = 0


# ============================================================
# PDF 解析结果数据模型
# ============================================================

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageChunk:
    """单页解析结果。

    Attributes:
        page_number: 1-based 页码（方便自然理解）。
            注意：pymupdf4llm 返回 0-based，由 _parse_document() 转换为 1-based。
        markdown_text: 该页的 Markdown 文本（Layout 模式下已包含表格格式化）。
        metadata: 文档元数据，包含 file_path、page_count、page_number 等。
        toc_items: 指向该页的目录项列表，格式 [lvl, title, pagenumber(1-based)]。
        page_boxes: Layout 布局边界框列表，每项含 index / class / bbox / pos。
            class 可为 "text" / "title" / "table" / "picture" / "header" / "footer" 等。
            pos 为 tuple(start, stop)，用于从 markdown_text 中切片提取该区域文本。
    """
    page_number: int
    markdown_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    toc_items: list[list[Any]] = field(default_factory=list)
    page_boxes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PDFParseResult:
    """PDF 解析的完整结果。

    Attributes:
        source: 来源标识（文件路径字符串或自定义名称），用于日志和下游追溯。
        page_count: PDF 总页数。
        chunks: 按页分块的解析结果列表，顺序与原始页码一致。
    """
    source: str
    page_count: int
    chunks: list[PageChunk] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """拼接所有页面的 Markdown 文本，页间以双换行分隔。"""
        return "\n\n".join(chunk.markdown_text for chunk in self.chunks)
