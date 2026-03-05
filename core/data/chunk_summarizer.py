"""逐 Chunk 摘要模块。

使用 PydanticAI Agent + DeepSeek 对单个 Chunk 生成结构化摘要。
支持 context_brief 注入，实现上下文衔接。

依赖：
- pydantic_ai：Agent 编排、结构化输出
- core.data.models：Chunk, ChunkList
- core.data.summary_models：ChunkSummaryOutput
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from httpx import AsyncClient
import logfire
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.settings import ModelSettings

from core.data.exceptions import LLMResponseError
from core.data.models import Chunk
from core.data.summary_models import ChunkSummaryOutput

if TYPE_CHECKING:
    from core.data.models import ChunkMeta

# ── 常量 ──────────────────────────────────────────────
DEFAULT_MODEL: str = "deepseek-chat"
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_TEMPERATURE: float = 0.3
DEFAULT_MAX_TOKENS: int = 4096


@dataclass(frozen=True)
class SummarizeContext:
    """摘要上下文依赖，注入 PydanticAI Agent 的 deps。

    Attributes:
        context_brief: 前一个 Chunk 的 context_brief，None 表示当前为首块
        chapter_path: 当前 Chunk 的章节路径
        contained_chapters: 当前 Chunk 包含的章节列表（多章节场景）
        chunk_index: 当前 Chunk 在章节内的索引
    """

    context_brief: str | None
    chapter_path: list[str]
    contained_chapters: list[str] | None
    chunk_index: int


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


async def _run_agent(
    user_prompt: str,
    deps: SummarizeContext,
    model_settings: ModelSettings,
    api_key: str,
    model: str,
) -> ChunkSummaryOutput:
    """内部函数：运行 PydanticAI Agent。

    封装 agent 创建和运行调用，便于测试 mock。

    Args:
        user_prompt: 用户 prompt
        deps: 依赖上下文
        model_settings: 模型设置
        api_key: DeepSeek API Key
        model: DeepSeek 模型名称

    Returns:
        结构化摘要输出
    """
    # 创建 HTTP 客户端
    http_client = AsyncClient(timeout=60)
    try:
        # 初始化模型和 Provider
        chat_model = OpenAIChatModel(
            model,
            provider=DeepSeekProvider(
                api_key=api_key,
                http_client=http_client,
            ),
        )

        # 创建 Agent
        agent = Agent(
            chat_model,
            output_type=ChunkSummaryOutput,
            deps_type=SummarizeContext,
            model_settings=model_settings,
        )

        # 注册 system prompt
        @agent.system_prompt
        def system_prompt() -> str:
            return _build_system_prompt()

        # 注册 output validator
        @agent.output_validator
        async def validate_output(
            ctx: RunContext[SummarizeContext], output: ChunkSummaryOutput
        ) -> ChunkSummaryOutput:
            if not output.key_points:
                raise ModelRetry("key_points 不能为空，请重新生成")
            return output

        # 运行 Agent
        result = await agent.run(user_prompt, deps=deps, model_settings=model_settings)
        return result.output
    finally:
        await http_client.aclose()


def _build_system_prompt() -> str:
    """构建系统 prompt，包含摘要格式要求和上下文指引。

    Returns:
        系统 prompt 字符串
    """
    base = """你是一名专业的文档摘要分析师，专门处理A股上市公司年报、半年报、季报等公告文档。

## 输出格式要求

请严格按以下 JSON 结构输出：

```json
{
    "chapter_title": "章节标题",
    "chapter_path": ["章节路径"],
    "key_points": ["核心要点列表"],
    "detailed_summary": "详细摘要",
    "key_data": [
        {"label": "标签", "value": 数值, "unit": "单位", "period": {...}, "remark": "备注"}
    ],
    "context_brief": "精简上下文提示（3~5句话）"
}
```

## 关键数据（key_data）单位推荐

- 金额：元、万元、亿元
- 比例：%（百分比）、成（，如"三成"）
- 股数：股、万股、亿股
- 人数：人

## 上下文（context_brief）用途

context_brief 是前一 Chunk 的精简摘要，用于：
1. 保持多子块章节的叙事连贯性
2. 避免重复输出前文已提及的信息
3. 让当前摘要聚焦于本 Chunk 的新内容

请在生成摘要时适当参考 context_brief，避免重复。"""

    return base


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
    1. 构建系统 prompt（格式要求 + context_brief 用途说明 + key_data 指引）
    2. 注入 context_brief（如有）
    3. 注入 chapter_path + contained_chapters 信息
    4. 注入 Chunk 原文 markdown
    5. 调用 PydanticAI Agent，output_type=ChunkSummaryOutput
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

    # 构建模型设置
    model_settings = ModelSettings(
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # 构建用户 prompt
    user_prompt = _build_user_prompt(chunk, context)

    logfire.debug(
        "Calling LLM for chunk summarization",
        chapter_path=context.chapter_path,
        chunk_index=context.chunk_index,
    )

    try:
        result = await _run_agent(
            user_prompt, context, model_settings, api_key, model
        )
        return result
    except ModelRetry as e:
        logfire.warning("LLM output validation failed, retrying", error=str(e))
        raise LLMResponseError(f"LLM output validation failed: {e}") from e
    except Exception as e:
        logfire.error("LLM call failed", error=str(e), error_type=type(e).__name__)
        raise LLMResponseError(f"LLM call failed: {e}") from e
