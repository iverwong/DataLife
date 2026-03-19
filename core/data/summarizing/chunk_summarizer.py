"""逐 Chunk 摘要模块。

使用 AgentRunner + DeepSeek 对单个 Chunk 生成结构化摘要。
支持 context_brief 注入，实现上下文衔接。

依赖：
- core.agents：AgentRunner 编排
- core.data.models：Chunk, ChunkList
- core.data.summary_models：ChunkSummaryOutput
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import logfire
from pydantic_ai import ModelRetry

from core.agents import AgentRunner
from core.agents.summarizing import ChunkSummarizerConfig
from core.data.exceptions import LLMResponseError
from core.data.models import Chunk
from .summary_models import ChunkSummaryOutput, SummarizeContext

if TYPE_CHECKING:
    from core.data.models import ChunkMeta

# ── 常量 ──────────────────────────────────────────────
DEFAULT_MODEL: str = "deepseek-chat"
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_TEMPERATURE: float = 0.3
DEFAULT_MAX_TOKENS: int = 4096


def _extract_chapter_titles(
    contained_chapters: list[ChunkMeta] | None,
) -> list[str] | None:
    """从 ChunkMeta 列表提取章节标题字符串列表。

    Args:
        contained_chapters: Chunk.contained_chapters，可能是 None 或空列表

    Returns:
        章节标题字符串列表，或 None
    """
    if not contained_chapters:
        return None
    # 处理 list[str] 或 list[ChunkMeta] 两种情况（测试场景）
    titles: list[str] = []
    for item in contained_chapters:
        if isinstance(item, str):
            titles.append(item)
        elif hasattr(item, "title"):
            titles.append(item.title)
        # 忽略其他类型
    return titles if titles else None


def build_summarize_context(
    chunk: Chunk,
    previous_context_brief: str | None,
) -> SummarizeContext:
    """从 Chunk 和前文 context_brief 构建摘要上下文。

    Args:
        chunk: 当前待摘要的 Chunk
        previous_context_brief: 前一个 Chunk 的 context_brief，
            同一章节子块间传递；不同章节间传递同级上一章节的 context_brief。
            首块为 None。

    Returns:
        SummarizeContext 实例
    """
    contained_chapters = _extract_chapter_titles(chunk.contained_chapters)
    return SummarizeContext(
        context_brief=previous_context_brief,
        chapter_path=chunk.chapter_path,
        contained_chapters=contained_chapters,
        chunk_index=chunk.chunk_index,
    )


def _build_user_prompt(
    chunk: Chunk,
    context: SummarizeContext,
) -> str:
    """构建用户 prompt，注入上下文和 Chunk 内容。

    Args:
        chunk: 待摘要的 Chunk
        context: 摘要上下文

    Returns:
        用户 prompt 字符串
    """
    parts: list[str] = []

    # 注入 context_brief（如有）
    if context.context_brief:
        parts.append(f"【前文上下文】\n{context.context_brief}\n")

    # 注入章节路径
    chapter_path_str = " > ".join(context.chapter_path)
    parts.append(f"【当前章节路径】{chapter_path_str}\n")

    # 注入 contained_chapters 信息（如有，多章节场景）
    if context.contained_chapters and len(context.contained_chapters) > 1:
        chapters_str = "、".join(context.contained_chapters)
        parts.append(
            f"【本 Chunk 包含的章节】本段内容涵盖以下章节：{chapters_str}。请分别对各章节产出结构化摘要。\n"
        )

    # 注入 Chunk 原文
    parts.append(f"【正文内容】\n{chunk.text}")

    return "\n".join(parts)


async def summarize_chunk(
    chunk: Chunk,
    context: SummarizeContext,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    retries: int = DEFAULT_MAX_RETRIES,
) -> ChunkSummaryOutput:
    """对单个 Chunk 调用 DeepSeek 生成结构化摘要。

    流程：
    1. 构建 system prompt（通过 ChunkSummarizerConfig 配置）
    2. 注入 context_brief（如有）
    3. 注入 chapter_path + contained_chapters 信息
    4. 注入 Chunk 原文 markdown
    5. 调用 AgentRunner，output_type=ChunkSummaryOutput
    6. 返回验证后的结构化输出

    Args:
        chunk: 待摘要的 Chunk（包含 text, chapter_path, contained_chapters 等）
        context: 摘要上下文（含 context_brief、chapter_path 等）
        model: DeepSeek 模型名称，默认 deepseek-chat
        api_key: DeepSeek API Key，None 时从环境变量 DEEPSEEK_API_KEY 读取
        temperature: 生成温度，默认 0.3（摘要任务偏确定性）
        max_tokens: 最大输出 token 数
        retries: 失败重试次数

    Returns:
        ChunkSummaryOutput：结构化摘要输出

    Raises:
        LLMResponseError: LLM 返回为空或无法解析为目标结构
        SummarizationError: 其他摘要流程异常
    """
    # 获取 API Key（如未提供则从环境变量读取）
    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    # 构建用户 prompt
    user_prompt = _build_user_prompt(chunk, context)

    logfire.debug(
        "Calling LLM for chunk summarization",
        chapter_path=context.chapter_path,
        chunk_index=context.chunk_index,
    )

    # 构建 AgentRunner 配置
    config = ChunkSummarizerConfig(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        retries=retries,
    )

    try:
        async with AgentRunner(config, api_key) as runner:
            return await runner.run(user_prompt, deps=context)
    except ModelRetry as e:
        logfire.warning("LLM output validation failed, retrying", error=str(e))
        raise LLMResponseError(f"LLM output validation failed: {e}") from e
    except Exception as e:
        logfire.error(
            "LLM call failed", error=str(e), error_type=type(e).__name__
        )
        raise LLMResponseError(f"LLM call failed: {e}") from e
