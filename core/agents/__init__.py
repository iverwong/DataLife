"""Agent 注册中心：集中导出所有 agent 实例。"""
from core.agents.chapter_merger_agent import chapter_merger_agent
from core.agents.chunk_summarizer_agent import chunk_summarizer_agent

__all__ = [
    "chunk_summarizer_agent",
    "chapter_merger_agent",
]
