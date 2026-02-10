import os

import httpx
from aiolimiter import AsyncLimiter
from notion_client import AsyncClient


class AsyncRateLimitedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, *, max_rate: float, time_period: float = 60.0, **kwargs):
        super().__init__(**kwargs)
        self._limiter = AsyncLimiter(max_rate=max_rate, time_period=time_period)

    async def handle_async_request(self, request):
        async with self._limiter:
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
