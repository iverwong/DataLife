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
