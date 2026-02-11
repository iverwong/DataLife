"""
网络请求重试机制的通用工具模块

提供装饰器用于为异步函数添加指数退避重试逻辑，
主要用于处理 Notion API 调用和其他网络请求中的临时性故障。
"""

import asyncio
import functools
from typing import ParamSpec, TypeVar

import httpx
from loguru import logger

P = ParamSpec("P")
T = TypeVar("T")

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0  # 基础延迟秒数
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ReadError,
    httpx.WriteError,
)


def with_retry(
    max_retries: int = MAX_RETRIES, retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS
):
    """装饰器：为异步函数添加指数退避重试逻辑

    使用示例:
        @with_retry()
        async def my_network_call():
            return await some_api_call()

        @with_retry(max_retries=5)
        async def critical_call():
            return await critical_api_call()

    Args:
        max_retries: 最大重试次数，默认 3 次
        retryable_exceptions: 需要重试的异常类型元组，默认包含常见的 httpx 网络异常

    Returns:
        装饰后的异步函数，具备自动重试能力

    Raises:
        retryable_exceptions: 达到最大重试次数后，抛出最后一次的异常
        Exception: 遇到非可重试异常时，直接抛出
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        # 指数退避：1s, 2s, 4s, 8s...
                        delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                        logger.warning(
                            f"[重试] {func.__name__} 第 {attempt}/{max_retries} 次尝试，等待 {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    logger.exception(f"[重试] {func.__name__} 遇到网络错误")
                    if attempt >= max_retries:
                        logger.error(
                            f"[重试] {func.__name__} 已达到最大重试次数 ({max_retries})，放弃重试"
                        )
                        raise
                except Exception:
                    logger.exception(f"[重试] {func.__name__} 遇到非重试错误")
                    raise
            raise last_exception

        return wrapper

    return decorator
