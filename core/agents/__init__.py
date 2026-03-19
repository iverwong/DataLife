"""Agent 抽象层。

统一管理 PydanticAI Agent 的创建、配置和 HTTP 客户端生命周期。
"""

from __future__ import annotations

from core.agents.base import AgentConfig, AgentRunner
from core.agents.summarizing import ChunkSummarizerConfig, ChapterMergerConfig

__all__ = [
    "AgentConfig",
    "AgentRunner",
    "ChunkSummarizerConfig",
    "ChapterMergerConfig",
]
