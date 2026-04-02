"""Chunk 摘要 Agent。"""
from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from core.data.summarizing.summary_models import ChunkSummaryOutput, SummarizeContext

_SYSTEM_PROMPT = """你是一名专业的文档摘要分析师，专门处理A股上市公司年报、半年报、季报等公告文档。

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

chunk_summarizer_agent: Agent[SummarizeContext, ChunkSummaryOutput] = Agent(
    OpenAIChatModel("deepseek-chat", provider=DeepSeekProvider()),
    output_type=ChunkSummaryOutput,
    deps_type=SummarizeContext,
    instructions=_SYSTEM_PROMPT,
    retries=3,
)
