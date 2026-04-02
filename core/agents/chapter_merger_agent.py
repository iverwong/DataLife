"""章节合并 Agent。"""
from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from core.data.summarizing.summary_models import ChunkSummaryOutput

chapter_merger_agent: Agent[None, ChunkSummaryOutput] = Agent(
    OpenAIChatModel("deepseek-chat", provider=DeepSeekProvider()),
    output_type=ChunkSummaryOutput,
    retries=3,
)
