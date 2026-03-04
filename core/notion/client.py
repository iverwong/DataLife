from httpx import Request, Response


from aiolimiter import AsyncLimiter

from typing import override

import os

import httpx
import logfire
from notion_client import AsyncClient

from typing import ParamSpecKwargs


class AsyncRateLimitedTransport(httpx.AsyncHTTPTransport):
    """带速率限制的 HTTP 传输层

    使用 AsyncLimiter 实现令牌桶算法，控制请求速率。
    配置：每秒最多 3 个请求（符合 Notion API 限制）
    """

    def __init__(
        self, *, max_rate: float, time_period: float = 1.0, **kwargs: ParamSpecKwargs
    ):
        super().__init__(**kwargs)  # pyright: ignore[reportArgumentType]
        self._max_rate: float = max_rate
        self._time_period: float = time_period
        self._limiter: AsyncLimiter = AsyncLimiter(
            max_rate=max_rate, time_period=time_period
        )

    @override
    async def handle_async_request(self, request: Request) -> Response:
        async with self._limiter:
            return await super().handle_async_request(request)

    @override
    async def aclose(self):
        await super().aclose()


# 懒加载：httpx.AsyncClient 初始为 None，首次调用时创建
httpx_client: httpx.AsyncClient | None = None
_notion_client: AsyncClient | None = None


def get_httpx_client() -> httpx.AsyncClient:
    """获取 httpx.AsyncClient 实例（懒加载）。

    首次调用时创建客户端并缓存，后续调用直接返回。
    这样在测试环境中 import 模块时不会触发客户端创建。
    """
    global httpx_client
    if httpx_client is None:
        httpx_client = httpx.AsyncClient(
            transport=AsyncRateLimitedTransport(
                max_rate=3,  # 每秒3个请求
                time_period=1.0,  # 时间窗口1秒
            ),
            timeout=httpx.Timeout(30.0, connect=10.0),  # 总超时30秒，连接超时10秒
            follow_redirects=True,
        )
    return httpx_client


def get_notion_client() -> AsyncClient:
    """获取 Notion AsyncClient 实例（懒加载）。

    首次调用时创建客户端并缓存，后续调用直接返回。
    """
    global _notion_client
    if _notion_client is None:
        _notion_client = AsyncClient(
            client=get_httpx_client(), auth=os.getenv("NOTION_TOKEN")
        )
    return _notion_client


# 模块级 __getattr__ 实现懒加载访问（Python 3.7+）
# 这样 from core.notion.client import notion 会触发懒加载
def __getattr__(name: str):
    if name == "notion":
        return get_notion_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def close_client() -> None:
    """关闭 httpx.AsyncClient 客户端。

    提供幂等性保护：若客户端已关闭或从未创建，则跳过关闭操作。
    同时处理事件循环已关闭的情况。
    """
    global httpx_client, _notion_client

    # 懒加载模式下，客户端可能从未被创建
    if httpx_client is None:
        logfire.debug("httpx.AsyncClient 从未创建，跳过关闭")
        return

    if httpx_client.is_closed:
        logfire.debug("httpx.AsyncClient 已关闭，跳过")
        return

    try:
        await httpx_client.aclose()
        logfire.debug("httpx.AsyncClient 已关闭")
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            logfire.debug("事件循环已关闭，跳过 httpx 客户端关闭")
        else:
            raise
    finally:
        # 重置全局变量，以便下次可以重新创建
        httpx_client = None
        _notion_client = None


__all__ = ["close_client", "get_httpx_client", "get_notion_client"]
