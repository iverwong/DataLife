"""摘要结果 SQLAlchemy ORM 持久化模块。

与 Step 2 的 chunk_meta 表关联，存储摘要输出。
所有操作通过 get_session() 获取 session 执行。
"""
from __future__ import annotations

from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
)


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
