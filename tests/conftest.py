import os
import sys
import threading
from pathlib import Path

import pytest
import asyncio
from dotenv import load_dotenv


# 将项目根目录添加到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def event_loop():
    """创建session级别的事件循环."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_env():
    """加载测试环境变量（.dev.env）."""
    env_path = Path(__file__).parent.parent / ".dev.env"
    load_dotenv(env_path)
    return {
        "NOTION_TOKEN": os.getenv("NOTION_TOKEN"),
        "FLOW_DATABASE": os.getenv("FLOW_DATABASE"),
        "STOCK_POOL": os.getenv("STOCK_POOL"),
    }


@pytest.fixture
async def test_engine():
    """创建 :memory: + StaticPool 的测试引擎。

    StaticPool 确保所有操作共享同一连接（异步模式下 :memory: 的每个连接是独立空数据库）。
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from core.db.engine import configure_for_testing, dispose_engine
    from core.db.models import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False, "autocommit": False},
    )
    # 建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 注入全局
    configure_for_testing(engine)
    yield engine
    # 清理
    await dispose_engine()


@pytest.fixture
async def in_memory_db(test_engine):
    """测试用内存数据库 fixture（test_engine 的别名）。

    保留此名称以兼容旧测试代码。
    """
    return test_engine


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """pytest 会话结束钩子：在所有测试和 fixture 清理后执行。

    使用 asyncio.run() 创建全新事件循环来执行异步清理，
    避免 pytest-asyncio 事件循环已关闭导致的问题。
    """
    import asyncio as asyncio_module
    from core.notion import client as notion_client_module
    from core.db import engine as db_engine

    async def _cleanup() -> None:
        """执行异步资源清理。"""
        # 关闭 httpx 客户端
        await notion_client_module.close_client()
        # 关闭数据库引擎
        await db_engine.dispose_engine()

    try:
        asyncio_module.run(_cleanup())
    except RuntimeError as e:
        # 如果 asyncio.run() 失败（httpx 绑定旧循环引用导致 aclose() 挂起），
        # 回退到同步强制关闭传输层
        if "Event loop is closed" in str(e):
            # 防御性兜底：访问私有 API 关闭传输层
            # 注意：httpx 版本升级时需验证此调用仍然有效
            try:
                client = notion_client_module.httpx_client
                if client is not None and not client.is_closed:
                    # pyright: ignore[reportPrivateImportUsage]
                    client._transport.close()
            except Exception as cleanup_error:
                import logging

                logging.warning(
                    f"Failed to close httpx transport layer: {cleanup_error}"
                )

            # 单独执行 dispose_engine（不依赖 asyncio.run）
            try:
                loop = asyncio_module.new_event_loop()
                asyncio_module.set_event_loop(loop)
                loop.run_until_complete(db_engine.dispose_engine())
            except Exception as db_error:
                logging.warning(f"Failed to close database: {db_error}")
        else:
            raise

    # 调试：打印当前线程状态（仅在测试失败时查看）
    if exitstatus != 0:
        non_daemon_threads = [
            t for t in threading.enumerate() if not t.daemon
        ]
        import logging

        logging.debug(
            f"pytest_sessionfinish: non-daemon threads: "
            f"{[t.name for t in non_daemon_threads]}"
        )
