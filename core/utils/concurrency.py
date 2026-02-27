"""统一并发控制模块。

提供基于 asyncio.Semaphore 的并发限制器，用于控制外部 HTTP 请求的并发数量，
防止资源耗尽（网络连接、内存等）。

注意：Notion API 调用已通过 aiolimiter 实现速率限制，无需额外并发控制。
"""

import asyncio
from collections.abc import Awaitable, Sequence
from typing import TypeVar

import logfire

# 巨潮资讯网 API 并发限制
CNINFO_CONCURRENCY = 5
"""巨潮资讯网 API 最大并发数。"""

# PDF 下载并发限制
PDF_DOWNLOAD_CONCURRENCY = 3
"""PDF 文件下载最大并发数。"""

# 模块级别的 Semaphore 实例（惰性初始化）
_cninfo_semaphore: asyncio.Semaphore | None = None
_pdf_download_semaphore: asyncio.Semaphore | None = None


def get_cninfo_semaphore() -> asyncio.Semaphore:
    """获取巨潮资讯网 API 的并发限制器。

    采用惰性初始化，确保在事件循环中首次调用时创建。

    Returns:
        用于限制巨潮 API 并发的 Semaphore 实例。
    """
    global _cninfo_semaphore
    if _cninfo_semaphore is None:
        _cninfo_semaphore = asyncio.Semaphore(CNINFO_CONCURRENCY)
        logfire.debug(
            "巨潮 API 并发限制器初始化: 最大 {count} 并发", count=CNINFO_CONCURRENCY
        )
    return _cninfo_semaphore


def get_pdf_download_semaphore() -> asyncio.Semaphore:
    """获取 PDF 下载的并发限制器。

    采用惰性初始化，确保在事件循环中首次调用时创建。

    Returns:
        用于限制 PDF 下载并发的 Semaphore 实例。
    """
    global _pdf_download_semaphore
    if _pdf_download_semaphore is None:
        _pdf_download_semaphore = asyncio.Semaphore(PDF_DOWNLOAD_CONCURRENCY)
        logfire.debug(
            "PDF 下载并发限制器初始化: 最大 {count} 并发",
            count=PDF_DOWNLOAD_CONCURRENCY,
        )
    return _pdf_download_semaphore


T = TypeVar("T")


async def with_concurrency_limit(
    semaphore: asyncio.Semaphore,
    coro: Awaitable[T],
) -> T:
    """在并发限制下执行协程。

    Args:
        semaphore: 用于控制并发的 Semaphore 实例。
        coro: 要执行的协程。

    Returns:
        协程的返回值。
    """
    async with semaphore:
        return await coro


async def gather_with_concurrency(
    semaphore: asyncio.Semaphore,
    tasks: Sequence[Awaitable[T]],
) -> list[T]:
    """在并发限制下批量执行协程。

    Args:
        semaphore: 用于控制并发的 Semaphore 实例。
        tasks: 要执行的协程列表。

    Returns:
        所有协程的返回值列表。
    """
    limited_tasks = [with_concurrency_limit(semaphore, task) for task in tasks]
    return await asyncio.gather(*limited_tasks)


async def gather_with_concurrency_and_exceptions(
    semaphore: asyncio.Semaphore,
    tasks: Sequence[Awaitable[T]],
) -> list[T | BaseException]:
    """在并发限制下批量执行协程，允许异常返回。

    Args:
        semaphore: 用于控制并发的 Semaphore 实例。
        tasks: 要执行的协程列表。

    Returns:
        所有协程的返回值或异常列表。
    """
    limited_tasks = [with_concurrency_limit(semaphore, task) for task in tasks]
    return await asyncio.gather(*limited_tasks, return_exceptions=True)


def reset_semaphores() -> None:
    """重置所有 Semaphore 实例。

    主要用于测试环境，确保每次测试使用独立的 Semaphore。
    """
    global _cninfo_semaphore, _pdf_download_semaphore
    _cninfo_semaphore = None
    _pdf_download_semaphore = None
    logfire.debug("并发限制器已重置")


__all__ = [
    "CNINFO_CONCURRENCY",
    "PDF_DOWNLOAD_CONCURRENCY",
    "get_cninfo_semaphore",
    "get_pdf_download_semaphore",
    "with_concurrency_limit",
    "gather_with_concurrency",
    "gather_with_concurrency_and_exceptions",
    "reset_semaphores",
]
