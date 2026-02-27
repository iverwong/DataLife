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
# PDF 解析结果的数据模型
# ============================================================


from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedPage:
    """单页 PDF 解析结果。

    Attributes:
        page_number: 1-based 页码。
        text: 该页提取的 Markdown 文本。
        tables: 该页检测到的表格元信息列表，每项含 bbox/row_count/col_count。
        toc_items: 指向该页的目录条目列表，格式 [level, title, page_number]。
        metadata: 文档级元数据（file_path, page_count 等），来自 pymupdf4llm。
    """

    page_number: int
    text: str
    tables: list[dict] = field(default_factory=list)
    toc_items: list[list] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    """整份 PDF 文档的解析结果。

    Attributes:
        source: 来源标识（文件路径或公告标题）。
        pages: 按页码排列的解析结果列表。
        total_pages: 文档总页数。
    """

    source: str
    pages: list[ParsedPage]
    total_pages: int

    @property
    def full_text(self) -> str:
        """拼接所有页面的 Markdown 文本，页间用分隔符隔开。"""
        return "\n\n---\n\n".join(p.text for p in self.pages if p.text.strip())


__all__ = [
    # 原有 Pydantic 模型
    "StockItem",
    "StockListResponse",
    "AnnouncementItem",
    "AnnouncementsResponse",
    # 新增 PDF 解析数据模型
    "ParsedPage",
    "ParsedDocument",
]
