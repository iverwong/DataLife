"""DataLife 项目统一异常体系。

所有模块的自定义异常均应继承 DataLifeError，
便于上层统一捕获和日志记录。
"""

from typing import override


class DataLifeError(Exception):
    """DataLife 项目统一异常基类。

    Attributes:
        message: 错误描述。
        cause: 原始异常（可选）。
    """

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause: Exception | None = cause

    @override
    def __str__(self) -> str:
        base = super().__str__()
        if self.cause:
            return f"{base} (caused by {type(self.cause).__name__}: {self.cause})"
        return base
