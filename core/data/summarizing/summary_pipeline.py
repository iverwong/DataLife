"""摘要编排主管道。

端到端编排：ChunkList → 逐 Chunk 摘要 → 章节合并 → 文档拼接 → 持久化。

依赖：
- core.data.models：ChunkList
- summarizing.summary_models：DocumentSummary
- summarizing.chunk_summarizer：summarize_chunk, build_summarize_context
- summarizing.chapter_merger：merge_chapter_summaries, build_single_chunk_chapter
- summarizing.summary_storage：save_*
"""
from __future__ import annotations

from typing import TYPE_CHECKING


from .summary_models import (
    DocumentSummary,
)

if TYPE_CHECKING:
    from core.data.models import ChunkList


async def summarize_document(
    chunk_list: "ChunkList",
    *,
    stock_code: str,
    report_date: str,
    model: str = "deepseek-chat",
    api_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries: int = 3,
    persist: bool = True,
    chunk_meta_ids: list[int] | None = None,  # type: ignore[assignment]
) -> "DocumentSummary":  # type: ignore[empty-body]
    """端到端文档摘要编排。

    完整流程：
    1. 遍历 ChunkList 中的 Chunk（按文档顺序）
    2. 对每个 Chunk 构建 SummarizeContext（注入前一块的 context_brief）
       - 同一章节子块间：传递前一子块的 context_brief
       - 不同章节间：传递同级上一章节最后一个子块的 context_brief
    3. 调用 summarize_chunk 获取 ChunkSummaryOutput
    4. 按章节分组：
       - 单 Chunk 章节 → build_single_chunk_chapter（路径 1）
       - 多 Chunk 章节 → merge_chapter_summaries（路径 2）
    5. 各章节摘要按原文顺序拼接
    6. 汇总 all_key_points 和 all_key_data
    7. 构建 DocumentSummary
    8. 如果 persist=True，写入 SQLite

    Args:
        chunk_list: Step 2 产出的 ChunkList
        stock_code: 股票代码，用于存储关联
        report_date: 报告日期
        model: DeepSeek 模型名称
        api_key: API Key
        temperature: 生成温度
        max_tokens: 最大输出 token
        retries: 重试次数
        persist: 是否持久化到 SQLite
        chunk_meta_ids: 每个 Chunk 对应的 chunk_meta_id 列表，按索引对应。
            当 persist=True 时，用于 per-chunk 持久化调用 save_chunk_summary。

    Returns:
        DocumentSummary：完整文档结构化摘要

    Raises:
        SummarizationError: 摘要流程异常
        SummaryStorageError: 持久化失败（仅 persist=True 时）
    """
    raise NotImplementedError("Contract declaration only")
