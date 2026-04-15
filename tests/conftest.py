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
    return {}


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """pytest 会话结束钩子：在所有测试和 fixture 清理后执行。

    使用 asyncio.run() 创建全新事件循环来执行异步清理，
    避免 pytest-asyncio 事件循环已关闭导致的问题。
    """
    import asyncio as asyncio_module
    from core.db import engine as db_engine

    async def _cleanup() -> None:
        """执行异步资源清理。"""
        # 关闭数据库引擎
        await db_engine.dispose_engine()

    try:
        asyncio_module.run(_cleanup())
    except RuntimeError as e:
        # 如果 asyncio.run() 失败，回退到同步强制关闭传输层
        if "Event loop is closed" in str(e):
            # 单独执行 dispose_engine（不依赖 asyncio.run）
            try:
                loop = asyncio_module.new_event_loop()
                asyncio_module.set_event_loop(loop)
                loop.run_until_complete(db_engine.dispose_engine())
            except Exception as db_error:
                import logging

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
