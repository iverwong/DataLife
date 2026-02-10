import os

import httpx
from aiolimiter import AsyncLimiter
from notion_client import AsyncClient


class AsyncRateLimitedTransport(httpx.BaseTransport):
    def __init__(self, *, max_rate: float, time_period: float = 60.0, **kwargs):
        self._transport = httpx.ASGITransport(**kwargs)
        self._limiter = AsyncLimiter(max_rate=max_rate, time_period=time_period)

    async def handle_request(self, request):
        async with self._limiter:
            return await self._transport.handle_request(request)

    async def close(self):
        await self._transport.close()


httpx_client = httpx.AsyncClient(
    transport=AsyncRateLimitedTransport(
        max_rate=3,  # 每秒3个请求
        time_period=1.0,  # 时间窗口1秒
    )
)

notion = AsyncClient(client=httpx_client, auth=os.getenv("NOTION_TOKEN"))
