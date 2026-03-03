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
        logfire.debug(
            "速率限制器初始化: {rate:.1f} 请求/秒", rate=max_rate / time_period
        )

    @override
    async def handle_async_request(self, request: Request) -> Response:
        async with self._limiter:
            return await super().handle_async_request(request)

    @override
    async def aclose(self):
        await super().aclose()


httpx_client = httpx.AsyncClient(
    transport=AsyncRateLimitedTransport(
        max_rate=3,  # 每秒3个请求
        time_period=1.0,  # 时间窗口1秒
    ),
    timeout=httpx.Timeout(30.0, connect=10.0),  # 总超时30秒，连接超时10秒
    follow_redirects=True,
)

notion = AsyncClient(client=httpx_client, auth=os.getenv("NOTION_TOKEN"))
logfire.debug("Notion AsyncClient 初始化完成")


async def close_client() -> None:
    """关闭 httpx.AsyncClient 客户端。

    提供幂等性保护：若客户端已关闭，则跳过关闭操作。
    同时处理事件循环已关闭的情况。
    """
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


__all__ = ["close_client"]
