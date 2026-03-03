import os
import sys
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


@pytest.fixture(scope="session", autouse=True)
def _cleanup_global_resources():
    """Session 级别的全局资源清理 fixture。

    注意：由于 session scope fixture 的 teardown 在事件循环关闭后执行，
    我们无法在这里安全地关闭 httpx 客户端。
    资源清理主要依赖 in_memory_db fixture 的 per-test teardown。
    """
    yield
