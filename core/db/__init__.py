"""本地 SQLite 数据库操作模块。

提供更新时间管理和基于 xxhash 的去重哈希功能，所有写操作通过事务保证原子性。
"""

import json
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import aiosqlite
import xxhash
import logfire

from ..models import NotionDate, UpdateRecordKey

db_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(db_dir, "notion.db")


@dataclass(frozen=True)
class HashContent:
    """去重哈希的输入内容。

    Attributes:
        data_type: 数据类型标识（如 "announcements"、"business"）。
        content: 用于计算哈希的原始内容字符串。
    """

    data_type: str
    content: str


@dataclass(frozen=True)
class HashContentWithHash:
    """带有计算后哈希值的去重内容。

    Attributes:
        data_type: 数据类型标识。
        content: 用于计算哈希的原始内容字符串。
        hash_value: 基于内容计算的 xxhash 值。
    """

    data_type: str
    content: str
    hash_value: str


db: aiosqlite.Connection | None = None


@asynccontextmanager
async def get_conn() -> AsyncIterator[aiosqlite.Connection]:
    """获取数据库连接的异步上下文管理器。

    使用全局单例连接，在上下文结束时自动提交事务，
    异常时自动回滚。

    Yields:
        活跃的数据库连接。
    """
    conn = await _get_db()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise


async def _get_db() -> aiosqlite.Connection:
    """获取或创建全局数据库连接。"""
    global db
    if db:
        return db
    db = await aiosqlite.connect(db_path)
    return db


async def init_db() -> None:
    """初始化数据库，创建所需的表结构。

    创建 update_records（更新时间记录）和 hash（去重哈希）两张表。
    """
    logfire.debug("初始化数据库连接")
    conn = await _get_db()
    _ = await conn.execute("""
            CREATE TABLE IF NOT EXISTS update_records (
                stock TEXT NOT NULL,
                key TEXT NOT NULL,
                update_time TEXT,
                PRIMARY KEY (stock, key)
                )
            """)
    # 创建Hash表
    _ = await conn.execute(
        """
            CREATE TABLE IF NOT EXISTS hash (
                hash TEXT PRIMARY KEY,
                create_at TEXT NOT NULL
                )
            """
    )
    await conn.commit()
    logfire.info("数据库初始化完成")


async def check_hash(data_list: list[HashContent]) -> list[HashContentWithHash]:
    """检查数据列表中的哈希值是否已存在于数据库中，返回未存在的数据项。

    Args:
        data_list: 待检查的哈希内容列表。

    Returns:
        仅包含数据库中尚未存在的数据项（附带计算后的哈希值）。
    """
    if not data_list:
        return []

    # 计算所有 Hash
    data_with_hash: list[HashContentWithHash] = []
    for item in data_list:
        content = json.dumps(
            {"data_type": item.data_type, "content": item.content},
            sort_keys=True,
            ensure_ascii=False,
        )
        hash_value = xxhash.xxh3_64_hexdigest(content.encode())
        data_with_hash.append(
            HashContentWithHash(
                data_type=item.data_type,
                content=item.content,
                hash_value=hash_value,
            )
        )

    # 在数据库中查询已存在的哈希
    async with get_conn() as conn:
        placeholder = ",".join("?" * len(data_with_hash))
        result = await conn.execute_fetchall(
            f"SELECT hash FROM hash WHERE hash IN ({placeholder})",
            tuple(each.hash_value for each in data_with_hash),
        )
        exist = {row[0] for row in result}

    # 过滤出不存在的数据
    return [each for each in data_with_hash if each.hash_value not in exist]


async def save_hash(data_list: list[str]) -> None:
    """将哈希值批量保存到数据库中。

    Args:
        data_list: 待保存的哈希值字符串列表。
    """
    async with get_conn() as conn:
        now = datetime.now().isoformat()
        _ = await conn.executemany(
            "INSERT INTO hash (hash, create_at) VALUES (?, ?)",
            [(each, now) for each in data_list],
        )


async def get_update_time(
    stocks: list[str], key: UpdateRecordKey
) -> dict[str, NotionDate | None]:
    """获取股票列表的更新时间记录，对缺失记录自动插入 NULL 行。

    Args:
        stocks: 股票代码列表。
        key: 业务键类型。

    Returns:
        字典，键为股票代码，值为对应的更新时间（可能为 None）。
    """
    async with get_conn() as conn:
        placeholder = ",".join("?" * len(stocks))
        result = await conn.execute_fetchall(
            f"SELECT stock, update_time FROM update_records WHERE stock IN ({placeholder}) AND key = ?",
            (*stocks, key),
        )

        result_dict = {row[0]: row[1] for row in result}

        missing_stocks = [stock for stock in stocks if stock not in result_dict]

        if missing_stocks:
            _ = await conn.executemany(
                "INSERT INTO update_records (stock, key, update_time) VALUES (?, ?, NULL)",
                tuple((stock, key) for stock in missing_stocks),
            )
            for stock in missing_stocks:
                result_dict[stock] = None

        return result_dict


async def set_update_time(
    stock: str, key: UpdateRecordKey, update_time: NotionDate | None
) -> None:
    """更新指定股票和键的更新时间记录。

    Args:
        stock: 股票代码。
        key: 业务键类型。
        update_time: 新的更新时间，可以为 None。

    Raises:
        ValueError: 如果未找到对应的记录（应先查询后更新）。
    """
    async with get_conn() as conn:
        cursor = await conn.execute(
            "UPDATE update_records SET update_time = ? WHERE stock = ? AND key = ?",
            (update_time, stock, key),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                f"未找到{stock}的{key}数据记录，业务逻辑错误，应先查询后更新"
            )


__all__ = [
    "HashContent",
    "HashContentWithHash",
    "get_conn",
    "init_db",
    "get_update_time",
    "set_update_time",
    "check_hash",
    "save_hash",
]
