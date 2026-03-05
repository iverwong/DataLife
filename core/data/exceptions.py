"""分块流程异常定义。

包含分块、章节检测、存储相关的自定义异常。
"""

from __future__ import annotations

from core.exceptions import DataLifeError


class ChunkingError(DataLifeError):
    """分块流程中的通用异常基类。"""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message, cause=cause)


class EmptyDocumentError(ChunkingError):
    """文档内容为空（无可分块的页面或文本）。"""

    pass


class ChapterDetectionError(ChunkingError):
    """章节识别过程中发生不可恢复的错误。"""

    pass


class StorageError(ChunkingError):
    """分块结果持久化读写失败。"""

    pass


# --- 摘要流程异常 ---


class SummarizationError(DataLifeError):
    """摘要流程基础异常。"""

    pass


class LLMResponseError(SummarizationError):
    """LLM 返回内容无法解析或为空。

    降级行为：重试 retries 次后抛出，由上层决定是否跳过该 Chunk。
    """

    pass


class ContextBriefError(SummarizationError):
    """上下文注入构建失败。

    降级行为：跳过 context_brief 注入，仅用当前 Chunk 独立摘要。
    记录 warning 日志，不中断流程。
    """

    pass


class ChapterMergeError(SummarizationError):
    """章节合并失败。

    降级行为：返回子块摘要的简单拼接（取各子块 detailed_summary 拼接），
    标记 degraded=True，记录 warning 日志。
    """

    pass


class SummaryStorageError(SummarizationError):
    """摘要存储读写异常。"""

    pass
