"""摘要相关 Agent 配置。

定义 ChunkSummarizerConfig 和 ChapterMergerConfig。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from pydantic_ai import Agent, ModelRetry, RunContext

from core.agents.base import AgentConfig
from core.data.summarizing.summary_models import ChunkSummaryOutput, SummarizeContext

# 从 chunk_summarizer.py 复制 system prompt 内容
_CHUNK_SUMMARIZER_SYSTEM_PROMPT = """你是一名专业的文档摘要分析师，专门处理A股上市公司年报、半年报、季报等公告文档。

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
- 比例：%（百分比）、成（如"三成"）
- 股数：股、万股、亿股
- 人数：人

## 上下文（context_brief）用途

context_brief 是前一 Chunk 的精简摘要，用于：
1. 保持多子块章节的叙事连贯性
2. 避免重复输出前文已提及的信息
3. 让当前摘要聚焦于本 Chunk 的新内容

请在生成摘要时适当参考 context_brief，避免重复。"""


@dataclass(frozen=True)
class ChunkSummarizerConfig(AgentConfig[SummarizeContext, ChunkSummaryOutput]):
    """逐 Chunk 摘要 Agent 配置。"""

    @override
    def get_output_type(self) -> type[ChunkSummaryOutput]:
        return ChunkSummaryOutput

    @override
    def get_instructions(self) -> str:
        return _CHUNK_SUMMARIZER_SYSTEM_PROMPT

    @override
    def get_deps_type(self) -> type | None:
        return SummarizeContext

    @override
    def configure_agent(
        self, agent: Agent[SummarizeContext, ChunkSummaryOutput]
    ) -> None:
        """注册 output_validator。"""

        @agent.output_validator
        async def validate_output(  # pyright: ignore[reportUnusedFunction] 仅通过装饰器注册
            _: RunContext[SummarizeContext], output: ChunkSummaryOutput
        ) -> ChunkSummaryOutput:
            if not output.key_points:
                raise ModelRetry("key_points 不能为空，请重新生成")
            return output


@dataclass(frozen=True)
class ChapterMergerConfig(AgentConfig[None, ChunkSummaryOutput]):
    """章节合并 Agent 配置。"""

    @override
    def get_output_type(self) -> type[ChunkSummaryOutput]:
        return ChunkSummaryOutput

    @override
    def get_instructions(self) -> str:
        return ""  # chapter_merger 当前无 instructions

    @override
    def get_deps_type(self) -> type | None:
        return None
