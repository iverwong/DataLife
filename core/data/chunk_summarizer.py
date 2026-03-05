"""逐 Chunk 摘要模块。

使用 PydanticAI Agent + DeepSeek 对单个 Chunk 生成结构化摘要。
支持 context_brief 注入，实现上下文衔接。

依赖：
- pydantic_ai：Agent 编排、结构化输出
- core.data.models：Chunk, ChunkList
- core.data.summary_models：ChunkSummaryOutput
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.data.summary_models import ChunkSummaryOutput

if TYPE_CHECKING:
    from core.data.models import Chunk

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
    raise NotImplementedError


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
    raise NotImplementedError
