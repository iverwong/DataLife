"""摘要结果 SQLite 持久化模块。

与 Step 2 的 chunk_meta 表关联，存储摘要输出。

依赖：
- aiosqlite
- core.data.summary_models：ChunkSummaryOutput, DocumentSummary, ChapterSummary
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.data.summary_models import ChapterSummary, ChunkSummaryOutput, DocumentSummary

# ── 常量 ──────────────────────────────────────────────
DEFAULT_DB_DIR: Path = Path("data")


async def init_summary_tables(db_path: Path = DEFAULT_DB_DIR / "datalife.db") -> None:
    """初始化摘要相关的 SQLite 表。

    创建以下表（IF NOT EXISTS）：
    - chunk_summary：逐 Chunk 摘要结果，外键关联 chunk_meta.id
        - id INTEGER PRIMARY KEY
        - chunk_meta_id INTEGER REFERENCES chunk_meta(id)
        - chapter_title TEXT NOT NULL
        - chapter_path TEXT NOT NULL (JSON array)
        - key_points TEXT NOT NULL (JSON array)
        - detailed_summary TEXT NOT NULL
        - key_data TEXT (JSON array of KeyDataItem)
        - context_brief TEXT NOT NULL
        - created_at TEXT NOT NULL (ISO 8601)
    - chapter_summary：章节级摘要（合并后或单 Chunk 直出）
        - id INTEGER PRIMARY KEY
        - stock_code TEXT NOT NULL
        - report_date TEXT NOT NULL
        - chapter_title TEXT NOT NULL
        - chapter_path TEXT NOT NULL (JSON array)
        - summary_json TEXT NOT NULL (完整 ChunkSummaryOutput JSON)
        - chunk_count INTEGER NOT NULL
        - created_at TEXT NOT NULL (ISO 8601)
    - document_summary：文档级摘要元信息
        - id INTEGER PRIMARY KEY
        - stock_code TEXT NOT NULL
        - report_date TEXT NOT NULL
        - total_chapters INTEGER NOT NULL
        - total_chunks_processed INTEGER NOT NULL
        - all_key_points TEXT NOT NULL (JSON array)
        - all_key_data TEXT NOT NULL (JSON array)
        - created_at TEXT NOT NULL (ISO 8601)

    Args:
        db_path: SQLite 数据库文件路径

    Raises:
        SummaryStorageError: 表创建失败
    """
    raise NotImplementedError


async def save_chunk_summary(
    chunk_meta_id: int,
    summary: "ChunkSummaryOutput",
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> int:
    """保存单个 Chunk 的摘要结果。

    Args:
        chunk_meta_id: chunk_meta 表中对应的记录 ID
        summary: Chunk 摘要输出
        db_path: 数据库路径

    Returns:
        插入记录的 ID

    Raises:
        SummaryStorageError: 写入失败
    """
    raise NotImplementedError


async def save_chapter_summary(
    chapter: "ChapterSummary",
    stock_code: str,
    report_date: str,
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> int:
    """保存章节级摘要结果。

    Args:
        chapter: 章节摘要
        stock_code: 股票代码
        report_date: 报告日期
        db_path: 数据库路径

    Returns:
        插入记录的 ID

    Raises:
        SummaryStorageError: 写入失败
    """
    raise NotImplementedError


async def save_document_summary(
    doc_summary: "DocumentSummary",
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> int:
    """保存完整文档摘要元信息。

    Args:
        doc_summary: 文档级摘要
        db_path: 数据库路径

    Returns:
        插入记录的 ID

    Raises:
        SummaryStorageError: 写入失败
    """
    raise NotImplementedError


async def load_document_summary(
    stock_code: str,
    report_date: str,
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> "DocumentSummary | None":
    """按股票代码和报告日期加载文档摘要。

    Args:
        stock_code: 股票代码
        report_date: 报告日期
        db_path: 数据库路径

    Returns:
        DocumentSummary 或 None（未找到）

    Raises:
        SummaryStorageError: 读取失败
    """
    raise NotImplementedError
