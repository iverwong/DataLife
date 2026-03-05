"""摘要结果 SQLite 持久化模块。

与 Step 2 的 chunk_meta 表关联，存储摘要输出。

依赖：
- aiosqlite
- core.data.summary_models：ChunkSummaryOutput, DocumentSummary, ChapterSummary
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
import logfire

from core.data.exceptions import SummaryStorageError
from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
)

if TYPE_CHECKING:
    pass

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
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with aiosqlite.connect(path) as db:
            # 创建 chunk_summary 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chunk_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_meta_id INTEGER REFERENCES chunk_meta(id),
                    chapter_title TEXT NOT NULL,
                    chapter_path TEXT NOT NULL,
                    key_points TEXT NOT NULL,
                    detailed_summary TEXT NOT NULL,
                    key_data TEXT,
                    context_brief TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 创建 chapter_summary 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chapter_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    chapter_title TEXT NOT NULL,
                    chapter_path TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 创建 document_summary 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS document_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    total_chapters INTEGER NOT NULL,
                    total_chunks_processed INTEGER NOT NULL,
                    all_key_points TEXT NOT NULL,
                    all_key_data TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(stock_code, report_date)
                )
            """)

            await db.commit()

        logfire.debug("摘要表初始化完成: {db_path}", db_path=str(path))
    except aiosqlite.Error as e:
        raise SummaryStorageError(f"初始化摘要表失败: {e}") from e


async def save_chunk_summary(
    chunk_meta_id: int,
    summary: ChunkSummaryOutput,
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
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """INSERT INTO chunk_summary
                   (chunk_meta_id, chapter_title, chapter_path, key_points,
                    detailed_summary, key_data, context_brief, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_meta_id,
                    summary.chapter_title,
                    json.dumps(summary.chapter_path, ensure_ascii=False),
                    json.dumps(summary.key_points, ensure_ascii=False),
                    summary.detailed_summary,
                    json.dumps([item.model_dump() for item in summary.key_data], ensure_ascii=False),
                    summary.context_brief,
                    created_at,
                ),
            )
            await db.commit()
            record_id = cursor.lastrowid
            if record_id is None:
                raise SummaryStorageError("无法获取插入记录的 ID")

        logfire.debug(
            "Chunk 摘要已保存: chunk_meta_id={chunk_meta_id}, record_id={record_id}",
            chunk_meta_id=chunk_meta_id,
            record_id=record_id,
        )
        return record_id
    except aiosqlite.Error as e:
        raise SummaryStorageError(f"保存 Chunk 摘要失败: {e}") from e


async def save_chapter_summary(
    chapter: ChapterSummary,
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
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """INSERT INTO chapter_summary
                   (stock_code, report_date, chapter_title, chapter_path,
                    summary_json, chunk_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    stock_code,
                    report_date,
                    chapter.chapter_title,
                    json.dumps(chapter.chapter_path, ensure_ascii=False),
                    chapter.summary.model_dump_json(),
                    chapter.chunk_count,
                    created_at,
                ),
            )
            await db.commit()
            record_id = cursor.lastrowid
            if record_id is None:
                raise SummaryStorageError("无法获取插入记录的 ID")

        logfire.debug(
            "章节摘要已保存: stock_code={stock_code}, report_date={report_date}, "
            "chapter={chapter_title}, record_id={record_id}",
            stock_code=stock_code,
            report_date=report_date,
            chapter_title=chapter.chapter_title,
            record_id=record_id,
        )
        return record_id
    except aiosqlite.Error as e:
        raise SummaryStorageError(f"保存章节摘要失败: {e}") from e


async def save_document_summary(
    doc_summary: DocumentSummary,
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
    # 从 source 字段提取 stock_code 和 report_date
    # source 格式: "600000_2024-12-31"
    parts = doc_summary.source.rsplit("_", 1)
    if len(parts) != 2:
        raise SummaryStorageError(f"无效的 source 格式: {doc_summary.source}")
    stock_code, report_date = parts

    created_at = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """INSERT OR REPLACE INTO document_summary
                   (stock_code, report_date, total_chapters, total_chunks_processed,
                    all_key_points, all_key_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    stock_code,
                    report_date,
                    doc_summary.total_chapters,
                    doc_summary.total_chunks_processed,
                    json.dumps(doc_summary.all_key_points, ensure_ascii=False),
                    json.dumps([item.model_dump() for item in doc_summary.all_key_data], ensure_ascii=False)
                    if doc_summary.all_key_data
                    else None,
                    created_at,
                ),
            )
            await db.commit()
            record_id = cursor.lastrowid
            if record_id is None:
                raise SummaryStorageError("无法获取插入记录的 ID")

        logfire.debug(
            "文档摘要已保存: stock_code={stock_code}, report_date={report_date}, "
            "chapters={total_chapters}, chunks={total_chunks}, record_id={record_id}",
            stock_code=stock_code,
            report_date=report_date,
            total_chapters=doc_summary.total_chapters,
            total_chunks=doc_summary.total_chunks_processed,
            record_id=record_id,
        )
        return record_id
    except aiosqlite.Error as e:
        raise SummaryStorageError(f"保存文档摘要失败: {e}") from e


async def load_document_summary(
    stock_code: str,
    report_date: str,
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> DocumentSummary | None:
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
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM document_summary
                   WHERE stock_code = ? AND report_date = ?""",
                (stock_code, report_date),
            )
            row = await cursor.fetchone()

        if row is None:
            logfire.debug(
                "文档摘要未找到: stock_code={stock_code}, report_date={report_date}",
                stock_code=stock_code,
                report_date=report_date,
            )
            return None

        # 反序列化
        source = f"{row['stock_code']}_{row['report_date']}"
        all_key_data: list[KeyDataItem] = []
        if row["all_key_data"]:
            items: list[dict[str, Any]] = json.loads(row["all_key_data"])
            for item_dict in items:
                all_key_data.append(KeyDataItem(**item_dict))

        all_key_points: list[str] = json.loads(row["all_key_points"])

        doc_summary = DocumentSummary(
            source=source,
            chapter_summaries=[],  # 从元信息表不存储章节详情，需单独查询
            all_key_points=all_key_points,
            all_key_data=all_key_data,
            total_chunks_processed=row["total_chunks_processed"],
            total_chapters=row["total_chapters"],
        )

        logfire.debug(
            "文档摘要已加载: stock_code={stock_code}, report_date={report_date}",
            stock_code=stock_code,
            report_date=report_date,
        )
        return doc_summary
    except aiosqlite.Error as e:
        raise SummaryStorageError(f"加载文档摘要失败: {e}") from e
    except json.JSONDecodeError as e:
        raise SummaryStorageError(f"文档摘要 JSON 解析失败: {e}") from e
