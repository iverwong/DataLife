"""摘要结果 SQLAlchemy ORM 持久化模块。

与 Step 2 的 chunk_meta 表关联，存储摘要输出。
所有操作通过 get_session() 获取 session 执行。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
)
from core.db import get_session
from core.db.models import (
    ChapterSummaryRecord,
    ChunkSummaryRecord,
    DocumentSummaryRecord,
)


class SummaryStorageError(Exception):
    """摘要存储异常。"""

    pass


async def save_chunk_summary(
    chunk_meta_id: int,
    summary: ChunkSummaryOutput,
) -> int:
    """保存单个 Chunk 的摘要结果。

    将 ChunkSummaryOutput 转为 ChunkSummaryRecord 并 add 到 session。
    JSON 序列化字段（key_points, chapter_path, key_data）使用 json.dumps。

    Args:
        chunk_meta_id: chunk_meta 表中对应的记录 ID。
        summary: Chunk 摘要输出。

    Returns:
        插入记录的 ID。

    Raises:
        SummaryStorageError: 写入失败。
    """
    try:
        # 注意：chapter_path, key_points, key_data 现在由 TypeDecorator 自动序列化
        record = ChunkSummaryRecord(
            chunk_meta_id=chunk_meta_id,
            chapter_title=summary.chapter_title,
            chapter_path=summary.chapter_path,
            key_points=summary.key_points,
            detailed_summary=summary.detailed_summary,
            key_data=summary.key_data or None,
            context_brief=summary.context_brief,
            created_at=datetime.now().isoformat(),
        )

        async with get_session() as session:
            session.add(record)
            await session.flush()
            return record.id
    except Exception as e:
        raise SummaryStorageError(f"保存 Chunk 摘要失败: {e}") from e


async def save_chapter_summary(
    chapter: ChapterSummary,
    stock_code: str,
    report_date: str,
) -> int:
    """保存章节级摘要结果。

    将 ChapterSummary 转为 ChapterSummaryRecord 并 add 到 session。

    Args:
        chapter: 章节摘要。
        stock_code: 股票代码。
        report_date: 报告日期。

    Returns:
        插入记录的 ID。

    Raises:
        SummaryStorageError: 写入失败。
    """
    try:
        # 注意：chapter_path 和 summary 现在由 TypeDecorator 自动序列化
        record = ChapterSummaryRecord(
            stock_code=stock_code,
            report_date=report_date,
            chapter_title=chapter.chapter_title,
            chapter_path=chapter.chapter_path,
            summary_json=chapter.summary,
            chunk_count=chapter.chunk_count,
            created_at=datetime.now().isoformat(),
        )

        async with get_session() as session:
            session.add(record)
            await session.flush()
            return record.id
    except Exception as e:
        raise SummaryStorageError(f"保存章节摘要失败: {e}") from e


async def save_document_summary(
    doc_summary: DocumentSummary,
) -> int:
    """保存完整文档摘要元信息。

    使用先查后更新/插入实现 upsert 语义（替代原 INSERT OR REPLACE），
    先按 (stock_code, report_date) 查询：
    - 已存在 → 更新所有字段
    - 不存在 → 插入新记录

    从 doc_summary.source 字段提取 stock_code 和 report_date（格式: "600000_2024-12-31"）。

    Args:
        doc_summary: 文档级摘要。

    Returns:
        插入/更新记录的 ID。

    Raises:
        SummaryStorageError: 写入失败或 source 格式无效。
    """
    try:
        # 从 source 解析 stock_code 和 report_date
        parts = doc_summary.source.split("_")
        if len(parts) != 2:
            raise SummaryStorageError(
                f"无效的 source 格式: {doc_summary.source}，期望格式: 'stock_code_report_date'"
            )
        stock_code = parts[0]
        report_date = parts[1]

        # 注意：all_key_points 和 all_key_data 现在由 TypeDecorator 自动序列化

        async with get_session() as session:
            # 查询已存在记录
            result = await session.execute(
                select(DocumentSummaryRecord)
                .where(DocumentSummaryRecord.stock_code == stock_code)
                .where(DocumentSummaryRecord.report_date == report_date)
            )
            record = result.scalar_one_or_none()

            if record is not None:
                # 更新
                record.total_chapters = doc_summary.total_chapters
                record.total_chunks_processed = doc_summary.total_chunks_processed
                record.all_key_points = doc_summary.all_key_points
                record.all_key_data = doc_summary.all_key_data or None
                record.created_at = datetime.now().isoformat()
            else:
                # 插入
                record = DocumentSummaryRecord(
                    stock_code=stock_code,
                    report_date=report_date,
                    total_chapters=doc_summary.total_chapters,
                    total_chunks_processed=doc_summary.total_chunks_processed,
                    all_key_points=doc_summary.all_key_points,
                    all_key_data=doc_summary.all_key_data or None,
                    created_at=datetime.now().isoformat(),
                )
                session.add(record)

            await session.flush()
            return record.id
    except SummaryStorageError:
        raise
    except Exception as e:
        raise SummaryStorageError(f"保存文档摘要失败: {e}") from e


async def load_document_summary(
    stock_code: str,
    report_date: str,
) -> DocumentSummary | None:
    """按股票代码和报告日期加载文档摘要。

    使用 select().where() 查询 DocumentSummaryRecord，反序列化为 DocumentSummary。
    JSON 字段（all_key_points, all_key_data）使用 json.loads 反序列化。

    Args:
        stock_code: 股票代码。
        report_date: 报告日期。

    Returns:
        DocumentSummary 或 None（未找到）。

    Raises:
        SummaryStorageError: 读取失败。
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                select(DocumentSummaryRecord)
                .where(DocumentSummaryRecord.stock_code == stock_code)
                .where(DocumentSummaryRecord.report_date == report_date)
            )
            record = result.scalar_one_or_none()

            if record is None:
                return None

            # 注意：all_key_points 和 all_key_data 现在由 TypeDecorator 自动反序列化
            # 直接使用 record 字段即可获得正确的 Python 对象
            return DocumentSummary(
                source=f"{record.stock_code}_{record.report_date}",
                chapter_summaries=[],  # 加载时不返回 chapter_summaries
                all_key_points=record.all_key_points or [],
                all_key_data=record.all_key_data or [],
                total_chunks_processed=record.total_chunks_processed,
                total_chapters=record.total_chapters,
            )
    except Exception as e:
        raise SummaryStorageError(f"加载文档摘要失败: {e}") from e
