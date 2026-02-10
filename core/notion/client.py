import logging
import os

import httpx
from aiolimiter import AsyncLimiter
from notion_client import AsyncClient

logger = logging.getLogger(__name__)


class AsyncRateLimitedTransport(httpx.AsyncHTTPTransport):
    """带速率限制的 HTTP 传输层

    使用 AsyncLimiter 实现令牌桶算法，控制请求速率。
    配置：每秒最多 3 个请求（符合 Notion API 限制）
    """

    def __init__(self, *, max_rate: float, time_period: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self._max_rate = max_rate
        self._time_period = time_period
        self._limiter = AsyncLimiter(max_rate=max_rate, time_period=time_period)
        logger.info(
            f"速率限制器初始化: max_rate={max_rate}/time_period={time_period}s "
            f"(约 {max_rate / time_period:.1f} 请求/秒)"
        )

    async def handle_async_request(self, request):
        logger.debug(f"[RateLimit] 请求: {request.method} {request.url.host}")
        async with self._limiter:
            logger.debug(f"[RateLimit] 放行请求: {request.method} {request.url.host}")
            return await super().handle_async_request(request)

    async def aclose(self):
        await super().aclose()


httpx_client = httpx.AsyncClient(
    transport=AsyncRateLimitedTransport(
        max_rate=3,  # 每秒3个请求
        time_period=1.0,  # 时间窗口1秒
    )
)

notion = AsyncClient(client=httpx_client, auth=os.getenv("NOTION_TOKEN"))
logger.info("Notion AsyncClient 初始化完成")
