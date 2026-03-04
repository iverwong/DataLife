import os
import sys
import threading
from pathlib import Path

import pytest
import asyncio
from dotenv import load_dotenv
from unittest.mock import patch


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


# 用于存储测试数据库单例连接
_test_db_conn = None


@pytest.fixture
def in_memory_db():
    """提供内存数据库连接，替换真实数据库。"""

    async def _get_test_db():
        global _test_db_conn
        import aiosqlite

        if _test_db_conn is not None:
            return _test_db_conn

        _test_db_conn = await aiosqlite.connect(":memory:")
        # 初始化测试数据库表结构
        await _test_db_conn.executescript("""
            CREATE TABLE IF NOT EXISTS update_records (
                stock TEXT NOT NULL,
                key TEXT NOT NULL,
                update_time TEXT,
                PRIMARY KEY (stock, key)
            );
            CREATE TABLE IF NOT EXISTS hash (
                hash TEXT PRIMARY KEY,
                create_at TEXT NOT NULL
            );
        """)
        return _test_db_conn

    with patch("core.db._get_db", _get_test_db):
        yield _get_test_db

    # Teardown: 关闭连接并重置全局状态
    import asyncio
    import core.db

    global _test_db_conn
    if _test_db_conn is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的事件循环，创建一个新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(_test_db_conn.close())
        _test_db_conn = None

    # 重置 core.db.db 全局变量
    if core.db.db is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(core.db.close_db())


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """pytest 会话结束钩子：在所有测试和 fixture 清理后执行。

    使用 asyncio.run() 创建全新事件循环来执行异步清理，
    避免 pytest-asyncio 事件循环已关闭导致的问题。
    """
    import core.db
    from core.notion import client as notion_client_module

    async def _cleanup() -> None:
        """执行异步资源清理。"""
        # 关闭 httpx 客户端
        await notion_client_module.close_client()
        # 关闭数据库连接
        await core.db.close_db()

    try:
        asyncio.run(_cleanup())
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

            # 单独执行 close_db（不依赖 asyncio.run）
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(core.db.close_db())
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
