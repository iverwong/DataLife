"""数据库引擎与会话管理。

提供模块级 Engine + async_sessionmaker + get_session() 上下文管理器。
所有写操作通过 get_session() 自动 commit/rollback。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DB_PATH: Path = Path("data/datalife.db")
"""默认数据库文件路径。"""

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine(db_path: Path = DEFAULT_DB_PATH) -> AsyncEngine:
    """创建 AsyncEngine 并注册 SQLite PRAGMA 钩子。

    Args:
        db_path: 数据库文件路径。

    Returns:
        配置好的 AsyncEngine 实例。

    注意：
        - connect_args={"autocommit": False} 禁用 sqlite3 legacy transaction mode，
          确保 DDL/SAVEPOINT 在事务内正确执行；Python 3.16 起此值将成为默认值。
        - 通过 event.listens_for 钩子启用 PRAGMA foreign_keys=ON（SQLite 默认不启用）。
    """
    # 确保数据库目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"autocommit": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType, reportUnusedParameter, reportUnusedFunction]
        """启用 SQLite 外键约束（默认关闭）。"""
        cursor = dbapi_connection.cursor()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        cursor.execute("PRAGMA foreign_keys=ON")  # pyright: ignore[reportUnknownMemberType]
        cursor.close()  # pyright: ignore[reportUnknownMemberType]

    return engine


def get_engine() -> AsyncEngine:
    """获取全局 AsyncEngine 单例。

    Returns:
        全局 AsyncEngine 实例。首次调用时使用 DEFAULT_DB_PATH 创建。
    """
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取全局 async_sessionmaker 单例。

    Returns:
        全局 async_sessionmaker 实例。

    注意：
        expire_on_commit=False 避免 commit 后访问属性触发隐式 IO。
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """获取数据库会话的异步上下文管理器。

    自动 commit/rollback 语义：
    - yield 后正常退出 → commit
    - yield 后异常 → rollback + re-raise

    Yields:
        活跃的 AsyncSession。
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """创建所有 ORM 模型对应的表（IF NOT EXISTS）。

    通过 Base.metadata.create_all 异步建表，替代现有各模块分散的手写 SQL 建表。
    使用 DEFAULT_DB_PATH 作为数据库路径，测试环境通过 configure_for_testing() 注入。
    """
    from core.db.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """释放全局 Engine 资源。

    替代现有 close_db()，统一资源生命周期（解决 P1-P4 问题）。
    提供幂等性保护：若 engine 已为 None，则跳过。
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None


# ── 测试支持 ────────────────────────────────────────────────


def configure_for_testing(engine: AsyncEngine) -> None:
    """替换全局 engine 和 session_factory，用于测试隔离。

    测试 conftest 调用此函数注入 :memory: + StaticPool 的测试引擎，
    使 get_session() 等函数自动使用测试数据库。

    Args:
        engine: 测试用 AsyncEngine（通常为 :memory: + StaticPool）。
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
