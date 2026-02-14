from httpx import Request, Response


from aiolimiter import AsyncLimiter

from typing import override

import os

import httpx
from loguru import logger
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
        logger.info(
            f"速率限制器初始化: max_rate={max_rate}/time_period={time_period}s (约 {max_rate / time_period:.1f} 请求/秒)"
        )

    @override
    async def handle_async_request(self, request: Request) -> Response:
        logger.debug(f"[RateLimit] 请求: {request.method} {request.url.host}")
        async with self._limiter:
            logger.debug(f"[RateLimit] 放行请求: {request.method} {request.url.host}")
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
logger.info("Notion AsyncClient 初始化完成")
