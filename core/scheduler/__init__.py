from apscheduler.schedulers.asyncio import AsyncIOScheduler  # pyright: ignore[reportMissingTypeStubs]

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
scheduler.start()


__all__ = ["scheduler"]
