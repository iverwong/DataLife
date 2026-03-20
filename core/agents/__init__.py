"""Agent 注册中心：集中导出所有 agent 实例。"""
from core.agents.chapter_merger_agent import chapter_merger_agent

__all__ = [
    "chunk_summarizer_agent",
    "chapter_merger_agent",
]


def __getattr__(name: str):
    """延迟加载 chunk_summarizer_agent 以避免循环依赖。"""
    if name == "chunk_summarizer_agent":
        import core.agents.chunk_summarizer_agent

        return core.agents.chunk_summarizer_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
