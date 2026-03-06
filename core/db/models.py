"""SQLAlchemy 2.0 ORM 模型定义。

所有数据库表结构的单一事实来源（Single Source of Truth）。
合并原 notion.db、chunks.db、datalife.db 为统一 data/datalife.db。
"""
from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from core.data.models import ChunkMeta
from core.data.summary_models import ChunkSummaryOutput, KeyDataItem
from core.db.types import (
    JsonChunkMetaList,
    JsonChunkSummaryOutput,
    JsonKeyDataItemList,
    JsonStringList,
)


class Base(AsyncAttrs, DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


# ── 原 notion.db 表 ──────────────────────────────────────────


class UpdateRecord(Base):
    """更新时间追踪记录。

    复合主键 (stock, key)，记录每只股票各业务键的最近更新时间。
    """
    __tablename__ = "update_records"

    stock: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    update_time: Mapped[str | None] = mapped_column(Text, nullable=True)


class HashRecord(Base):
    """内容去重哈希记录。

    基于 xxhash 的内容指纹，用于增量更新时跳过已处理数据。
    """
    __tablename__ = "hash"

    hash: Mapped[str] = mapped_column(Text, primary_key=True)
    create_at: Mapped[str] = mapped_column(Text, nullable=False)


# ── 原 chunks.db 表 ──────────────────────────────────────────


class ChunkMetaRecord(Base):
    """分块元信息持久化记录。

    每条记录对应一个逻辑分块（Chunk），存储章节、页码、token 数等元数据。
    Markdown 文本存储于文件系统，通过 md_file_path 关联。
    """
    __tablename__ = "chunk_meta"
    __table_args__ = (
        Index("ix_chunk_meta_stock_date", "stock_code", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    report_date: Mapped[str] = mapped_column(String, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_title: Mapped[str | None] = mapped_column(Text)
    chapter_path: Mapped[list[str] | None] = mapped_column(JsonStringList)
    contained_chapters: Mapped[list[ChunkMeta] | None] = mapped_column(JsonChunkMetaList)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(Text, nullable=False)
    needs_prior_summary: Mapped[int] = mapped_column(Integer, nullable=False)
    md_file_path: Mapped[str] = mapped_column(Text, nullable=False)

    # relationship：级联删除关联的摘要
    summaries: Mapped[list["ChunkSummaryRecord"]] = relationship(
        back_populates="chunk_meta", cascade="all, delete-orphan"
    )


# ── 原 datalife.db 表 ────────────────────────────────────────


class ChunkSummaryRecord(Base):
    """单 Chunk 摘要结果。

    外键关联 chunk_meta.id，存储 LLM 产出的结构化摘要。
    """
    __tablename__ = "chunk_summary"
    __table_args__ = (
        Index("ix_chunk_summary_meta_id", "chunk_meta_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_meta_id: Mapped[int] = mapped_column(ForeignKey("chunk_meta.id", ondelete="CASCADE"), nullable=False)
    chapter_title: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_path: Mapped[list[str]] = mapped_column(JsonStringList, nullable=False)
    key_points: Mapped[list[str]] = mapped_column(JsonStringList, nullable=False)
    detailed_summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_data: Mapped[list[KeyDataItem] | None] = mapped_column(JsonKeyDataItemList)
    context_brief: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    chunk_meta: Mapped["ChunkMetaRecord"] = relationship(back_populates="summaries")


class ChapterSummaryRecord(Base):
    """章节级摘要结果。

    合并后或单 Chunk 直出的章节摘要，按 (stock_code, report_date) 查询。
    """
    __tablename__ = "chapter_summary"
    __table_args__ = (
        Index("ix_chapter_summary_stock_date", "stock_code", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    report_date: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_title: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_path: Mapped[list[str]] = mapped_column(JsonStringList, nullable=False)
    summary_json: Mapped[ChunkSummaryOutput] = mapped_column(JsonChunkSummaryOutput, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class DocumentSummaryRecord(Base):
    """文档级摘要元信息。

    UNIQUE(stock_code, report_date) 确保每份报告只有一条文档摘要。
    """
    __tablename__ = "document_summary"
    __table_args__ = (
        UniqueConstraint("stock_code", "report_date", name="uq_doc_summary_stock_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    report_date: Mapped[str] = mapped_column(Text, nullable=False)
    total_chapters: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    all_key_points: Mapped[list[str]] = mapped_column(JsonStringList, nullable=False)
    all_key_data: Mapped[list[KeyDataItem] | None] = mapped_column(JsonKeyDataItemList)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
