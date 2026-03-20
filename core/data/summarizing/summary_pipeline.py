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

from collections import defaultdict
from typing import TYPE_CHECKING

import logfire

from core.data.exceptions import LLMResponseError, SummarizationError

from .chapter_merger import build_single_chunk_chapter, merge_chapter_summaries
from .chunk_summarizer import build_summarize_context, summarize_chunk
from .summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
)
from .summary_storage import (
    save_chapter_summary,
    save_document_summary,
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
) -> "DocumentSummary":
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
    logfire.debug(
        "Starting document summarization: stock={stock}, date={date}, chunks={count}",
        stock=stock_code,
        date=report_date,
        count=len(chunk_list.chunks),
    )

    # 1. 逐 Chunk 摘要
    chunk_summaries: list[ChunkSummaryOutput] = []

    # 记录失败 chunk：（index, error_message）
    failed_chunks: list[tuple[int, str]] = []

    # 维护每个章节最后一个子块的 context_brief
    # Problem 1 fix: 使用 tuple[str, ...] 作为 key，与 chapter_path 类型一致
    last_context_brief_by_chapter: dict[tuple[str, ...], str] = {}
    # 维护上一个章节最后子块的 context_brief
    last_chapter_brief: str | None = None
    # 记录上一个章节的 key（用于检测章节变化）
    # Problem 1 fix: 使用 tuple[str, ...] 而非 str，避免 tuple vs str 比较永远不相等
    last_chapter_key: tuple[str, ...] | None = None

    for i, chunk in enumerate(chunk_list.chunks):
        # 确定章节 key
        chapter_key = tuple(chunk.chapter_path)

        # 确定 previous_context_brief
        if chapter_key == last_chapter_key:
            # 同一章节：使用同章节上一个子块的 context_brief
            previous_context_brief = last_context_brief_by_chapter.get(chapter_key)
        elif chapter_key in last_context_brief_by_chapter:
            # 章节回跳（A→B→A）：使用该章节之前存储的 context_brief
            previous_context_brief = last_context_brief_by_chapter.get(chapter_key)
        else:
            # 新章节：使用上一个章节最后子块的 context_brief
            previous_context_brief = last_chapter_brief

        # Fallback: 如果 context_brief 仍为 None（失败 chunk 后章节 key 已更新但未存储），
        # 使用上一个成功的 context_brief
        if previous_context_brief is None:
            previous_context_brief = last_chapter_brief

        # 构建上下文
        context = build_summarize_context(chunk, previous_context_brief)

        # 调用摘要
        try:
            summary = await summarize_chunk(
                chunk,
                context,
                model=model,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                retries=retries,
            )
            chunk_summaries.append(summary)

            # 更新 context_brief 追踪
            # Problem 1 fix: 直接使用 tuple 作为 key，不再转为 str
            last_context_brief_by_chapter[chapter_key] = summary.context_brief
            last_chapter_brief = summary.context_brief
            last_chapter_key = chapter_key

            logfire.debug(
                "Chunk summarized: chapter={chapter}, index={idx}",
                chapter=chunk.chapter_path[-1],
                idx=chunk.chunk_index,
            )
        except (LLMResponseError, SummarizationError) as e:
            # 记录失败，继续处理下一个 Chunk
            failed_chunks.append((i, str(e)))
            logfire.warning(
                "Chunk {idx} summarization failed, skipping: {error}",
                idx=i, error=str(e),
            )
            # 不更新 context_brief 追踪 — 保持上一个成功的值
            # last_chapter_key 仍需更新以保持章节切换检测正确
            last_chapter_key = chapter_key
            continue

    # 2. 按章节分组
    # Problem 1 fix: 使用 tuple[str, ...] 作为 key
    chapter_groups: dict[tuple[str, ...], list[ChunkSummaryOutput]] = defaultdict(list)
    for summary in chunk_summaries:
        key = tuple(summary.chapter_path)
        chapter_groups[key].append(summary)

    # 3. 章节合并或直出
    chapter_summaries: list[ChapterSummary] = []

    # 保持原有章节顺序
    # Problem 1 fix: 使用 set[tuple[str, ...]]
    seen_chapters: set[tuple[str, ...]] = set()
    for summary in chunk_summaries:
        chapter_key = tuple(summary.chapter_path)
        if chapter_key in seen_chapters:
            continue
        seen_chapters.add(chapter_key)

        group = chapter_groups[chapter_key]
        if len(group) == 1:
            # 单 Chunk 章节：直出
            chapter_summary = build_single_chunk_chapter(group[0])
        else:
            # 多 Chunk 章节：合并
            chapter_summary = await merge_chapter_summaries(
                group,
                chapter_title=group[0].chapter_title,
                chapter_path=group[0].chapter_path,
                model=model,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                retries=retries,
            )

        chapter_summaries.append(chapter_summary)

    # 4. 汇总 all_key_points 和 all_key_data
    all_key_points: list[str] = []
    all_key_data: list[KeyDataItem] = []
    seen_points: set[str] = set()
    seen_labels: set[str] = set()

    for ch in chapter_summaries:
        for point in ch.summary.key_points:
            if point not in seen_points:
                all_key_points.append(point)
                seen_points.add(point)

        for data in ch.summary.key_data:
            if data.label not in seen_labels:
                all_key_data.append(data)
                seen_labels.add(data.label)

    # 5. 构建 DocumentSummary
    doc_summary = DocumentSummary(
        source=f"{stock_code}_{report_date}",
        chapter_summaries=chapter_summaries,
        all_key_points=all_key_points,
        all_key_data=all_key_data,
        total_chunks_processed=len(chunk_list.chunks),
        total_chapters=len(chapter_summaries),
    )

    # 6. 持久化（如需要）
    if persist:
        # 保存章节摘要
        for chapter_summary in chapter_summaries:
            await save_chapter_summary(
                chapter_summary,
                stock_code=stock_code,
                report_date=report_date,
            )

        # 保存文档摘要
        await save_document_summary(doc_summary)

        logfire.debug(
            "Document summary persisted: stock={stock}, date={date}",
            stock=stock_code,
            date=report_date,
        )

    # Problem 2 fix: 报告失败的 chunk
    if failed_chunks:
        logfire.warning(
            "Document summarization completed with {count} failed chunks: {details}",
            count=len(failed_chunks),
            details=failed_chunks,
        )

    return doc_summary
