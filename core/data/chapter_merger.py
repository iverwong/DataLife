"""章节级摘要合并模块。

处理多 Chunk 章节的摘要合并：收集该章节所有子块的摘要，
调用 LLM 合并为一份统一的章节摘要。

依赖：
- pydantic_ai：Agent 编排
- core.data.summary_models：ChunkSummaryOutput, ChapterSummary
"""
from __future__ import annotations

from core.data.summary_models import ChapterSummary, ChunkSummaryOutput


async def merge_chapter_summaries(
    sub_summaries: list[ChunkSummaryOutput],
    chapter_title: str,
    chapter_path: list[str],
    *,
    model: str = "deepseek-chat",
    api_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries: int = 3,
) -> ChapterSummary:
    """将同一章节的多个子块摘要合并为章节级摘要。

    路径 2 逻辑：收集子块的 detailed_summary + key_points + key_data，
    调用 LLM 生成统一的章节摘要。LLM 只接收摘要文本，不接收原文。

    Args:
        sub_summaries: 同一章节下所有子块的 ChunkSummaryOutput，按原文顺序排列
        chapter_title: 章节标题
        chapter_path: 章节路径
        model: DeepSeek 模型名称
        api_key: API Key
        temperature: 生成温度
        max_tokens: 最大输出 token
        retries: 重试次数

    Returns:
        ChapterSummary：合并后的章节级摘要

    Raises:
        ChapterMergeError: 合并失败时抛出。
            降级行为：返回子块摘要拼接结果，chapter_count 仍为实际子块数。
        LLMResponseError: LLM 返回异常

    Note:
        当 sub_summaries 长度为 1 时，直接包装为 ChapterSummary 返回，不调用 LLM。
    """
    raise NotImplementedError


def build_single_chunk_chapter(
    summary: ChunkSummaryOutput,
) -> ChapterSummary:
    """将单 Chunk 章节的摘要包装为 ChapterSummary（路径 1）。

    Args:
        summary: 单 Chunk 的摘要输出

    Returns:
        ChapterSummary，chunk_count=1
    """
    raise NotImplementedError
