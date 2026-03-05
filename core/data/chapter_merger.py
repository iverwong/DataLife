"""章节级摘要合并模块。

处理多 Chunk 章节的摘要合并：收集该章节所有子块的摘要，
调用 LLM 合并为一份统一的章节摘要。

依赖：
- pydantic_ai：Agent 编排
- core.data.summary_models：ChunkSummaryOutput, ChapterSummary
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx
import logfire
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.settings import ModelSettings

from core.data.exceptions import LLMResponseError
from core.data.summary_models import ChapterSummary, ChunkSummaryOutput, KeyDataItem

if TYPE_CHECKING:
    pass

# ──────────────────────────────────────────────
DEFAULT_MODEL: str = "deepseek-chat"
DEFAULT_TEMPERATURE: float = 0.3
DEFAULT_MAX_TOKENS: int = 4096


def build_single_chunk_chapter(
    summary: ChunkSummaryOutput,
) -> ChapterSummary:
    """将单 Chunk 章节的摘要包装为 ChapterSummary（路径 1）。

    Args:
        summary: 单 Chunk 的摘要输出

    Returns:
        ChapterSummary，chunk_count=1
    """
    return ChapterSummary(
        chapter_title=summary.chapter_title,
        chapter_path=summary.chapter_path,
        summary=summary,
        chunk_count=1,
    )


async def _run_merge_agent(
    sub_summaries: list[ChunkSummaryOutput],
    chapter_title: str,
    chapter_path: list[str],
    *,
    model: str,
    api_key: str | None,
    temperature: float,
    max_tokens: int,
) -> ChunkSummaryOutput:
    """内部函数：调用 LLM 合并多个子块摘要。

    Args:
        sub_summaries: 子块摘要列表
        chapter_title: 章节标题
        chapter_path: 章节路径
        model: 模型名称
        api_key: API Key
        temperature: 温度
        max_tokens: 最大 token

    Returns:
        合并后的 ChunkSummaryOutput
    """
    # 构建合并 prompt
    prompt_parts = [
        "请合并以下章节的多个子块摘要，统一生成章节级摘要。\n",
        f"章节标题：{chapter_title}\n",
        f"章节路径：{' > '.join(chapter_path)}\n\n",
        "子块摘要内容：\n",
    ]

    for i, sub in enumerate(sub_summaries, 1):
        prompt_parts.append(f"\n--- 子块 {i} ---\n")
        prompt_parts.append(f"详细摘要：{sub.detailed_summary}\n")
        if sub.key_points:
            prompt_parts.append(f"核心要点：{', '.join(sub.key_points)}\n")
        if sub.key_data:
            data_strs = [
                f"{d.label}: {d.value} {d.unit}" if d.value else d.label
                for d in sub.key_data
            ]
            prompt_parts.append(f"关键数据：{', '.join(data_strs)}\n")

    prompt_parts.append(
        "\n\n请生成统一的章节摘要，包含："
        "chapter_title, chapter_path, key_points(3-5条), "
        "detailed_summary(综合各子块内容), key_data(合并去重), "
        + "context_brief(精简上下文供后续章节使用)"
    )

    user_prompt = "".join(prompt_parts)

    # 获取 API Key
    if api_key is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise LLMResponseError("DEEPSEEK_API_KEY not found in environment")

    # 创建 Agent
    http_client = httpx.AsyncClient(timeout=60)
    model_instance = OpenAIChatModel(
        model,
        provider=DeepSeekProvider(api_key=api_key, http_client=http_client),
    )

    agent = Agent(
        model_instance,
        output_type=ChunkSummaryOutput,
    )

    logfire.debug(
        "Running merge agent for chapter: {chapter_title}, sub_count={count}",
        chapter_title=chapter_title,
        count=len(sub_summaries),
    )

    result = await agent.run(
        user_prompt,
        model_settings=ModelSettings(temperature=temperature, max_tokens=max_tokens),
    )

    return result.output


async def merge_chapter_summaries(
    sub_summaries: list[ChunkSummaryOutput],
    chapter_title: str,
    chapter_path: list[str],
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
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
    # 路径 1：单子块直接包装
    if len(sub_summaries) == 1:
        return build_single_chunk_chapter(sub_summaries[0])

    # 路径 2：多子块合并
    try:
        merged = await _run_merge_agent(
            sub_summaries,
            chapter_title,
            chapter_path,
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return ChapterSummary(
            chapter_title=merged.chapter_title,
            chapter_path=merged.chapter_path,
            summary=merged,
            chunk_count=len(sub_summaries),
        )
    except Exception as e:
        # 降级处理：拼接子块摘要
        logfire.warning(
            "Chapter merge failed, falling back to concatenation: {error}",
            error=str(e),
        )

        # 拼接 detailed_summary
        detailed_parts = [sub.detailed_summary for sub in sub_summaries]
        concatenated_summary = "\n\n".join(detailed_parts)

        # 合并 key_points（去重）
        all_points: list[str] = []
        seen_points: set[str] = set()
        for sub in sub_summaries:
            for point in sub.key_points:
                if point not in seen_points:
                    all_points.append(point)
                    seen_points.add(point)

        # 合并 key_data（去重，基于 label）
        all_data: list[KeyDataItem] = []
        seen_labels: set[str] = set()
        for sub in sub_summaries:
            for data in sub.key_data:
                if data.label not in seen_labels:
                    all_data.append(data)
                    seen_labels.add(data.label)

        # 构建降级版 ChapterSummary
        fallback_output = ChunkSummaryOutput(
            chapter_title=chapter_title,
            chapter_path=chapter_path,
            key_points=all_points[:5] if all_points else ["（合并失败，仅拼接）"],
            detailed_summary=concatenated_summary,
            key_data=all_data,
            context_brief=f"{chapter_title}由{len(sub_summaries)}个子块拼接而成。",
        )

        return ChapterSummary(
            chapter_title=chapter_title,
            chapter_path=chapter_path,
            summary=fallback_output,
            chunk_count=len(sub_summaries),
        )
