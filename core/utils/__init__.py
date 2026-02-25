"""通用工具模块。

提供跨模块共享的工具函数和基础设施。
"""

from .concurrency import (
    CNINFO_CONCURRENCY,
    PDF_DOWNLOAD_CONCURRENCY,
    gather_with_concurrency,
    gather_with_concurrency_and_exceptions,
    get_cninfo_semaphore,
    get_pdf_download_semaphore,
    reset_semaphores,
    with_concurrency_limit,
)

__all__ = [
    "CNINFO_CONCURRENCY",
    "PDF_DOWNLOAD_CONCURRENCY",
    "gather_with_concurrency",
    "gather_with_concurrency_and_exceptions",
    "get_cninfo_semaphore",
    "get_pdf_download_semaphore",
    "reset_semaphores",
    "with_concurrency_limit",
]
