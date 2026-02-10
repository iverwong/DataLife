import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, NotRequired, TypedDict

import aiosqlite
import xxhash

from ..models import NotionDate

db_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(db_dir, "notion.db")

# 配置项中需要更新的键
KEYS = Literal["business", "announcements"]


class HashContent(TypedDict):
    data_type: str
    content: str
    hash: NotRequired[str]


db = None


@asynccontextmanager
async def get_conn():
    """
    异步上下文管理器函数，用于获取 SQLite 数据库连接。
    该函数通过上下文管理器的方式管理数据库连接的生命周期，确保在使用完毕后正确提交事务或回滚，
    并关闭数据库连接。适用于需要安全操作数据库的场景。

    使用方式：
        async with get_conn() as conn:
            # 在此处执行数据库操作
            cursor = await conn.execute('SELECT * FROM table')
            result = await cursor.fetchall()

    注意事项：
        - 如果在使用过程中发生异常，事务会自动回滚。
        - 无论是否发生异常，连接都会在最后被关闭。
    """
    conn = db or await _get_db()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise


async def _get_db():
    global db
    if db:
        return db
    db = await aiosqlite.connect(db_path)
    return db


async def init_db():
    """
    同步初始化数据库，创建所需的表结构。

    该函数通过获取数据库连接，创建两个表：
    1. `update_records` 表：用于存储股票更新记录，包含股票代码、键值和更新时间。
    2. `hash`表：用于存储哈希值及其创建时间。

    参数:
        无

    返回值:
        无
    """
    conn = await _get_db()
    await conn.execute("""
            CREATE TABLE IF NOT EXISTS update_records (
                stock TEXT NOT NULL,
                key TEXT NOT NULL,
                update_time TEXT,
                PRIMARY KEY (stock, key)
                )
            """)
    # 创建Hash表
    await conn.execute(
        """
            CREATE TABLE IF NOT EXISTS hash (
                hash TEXT PRIMARY KEY,
                create_at TEXT NOT NULL
                )
            """
    )
    await conn.commit()


async def check_hash(data_list: list[HashContent]) -> list[HashContent]:
    """
    检查数据列表中的哈希值是否已存在于数据库中，并返回未存在的数据项。

    参数:
        data_list (list[HashContent]): 包含待检查数据的列表，每个元素应为可序列化的字典对象。

    返回:
        list: 过滤后的数据列表，仅包含哈希值未在数据库中存在的数据项。
    """
    # 如果数据列表为空，直接返回空列表
    if not data_list:
        return []

    # 计算所有Hash
    data_with_hash = []
    for item in data_list:
        content = json.dumps(item, sort_keys=True, ensure_ascii=False)
        hash_content = xxhash.xxh3_64_hexdigest(content.encode())
        data_with_hash.append({**item, "hash": hash_content})

    # 在数据库中查询
    async with get_conn() as conn:
        placeholder = ",".join("?" * len(data_with_hash))
        result = await conn.execute_fetchall(
            f"""
            SELECT hash FROM hash WHERE hash IN ({placeholder})
            """,
            tuple(each.get("hash") for each in data_with_hash),
        )
        exist = {row[0] for row in result}

    # 去重
    filtered_data = [each for each in data_with_hash if each["hash"] not in exist]

    return filtered_data


async def save_hash(data_list: list[HashContent]) -> None:
    """
    将哈希数据批量保存到数据库中。

    参数:
        data_list (list[HashContent]): 包含哈希内容的列表，每个元素应包含一个 "hash" 键。

    返回值:
        无返回值。

    功能说明:
        该函数通过数据库连接，将传入的哈希数据列表批量插入到名为 "hash" 的表中。
        每条记录包含哈希值和当前时间戳（ISO格式）。
    """
    async with get_conn() as conn:
        now = datetime.now().isoformat()
        await conn.executemany(
            "INSERT INTO hash (hash, create_at) VALUES (?, ?)",
            [(each.get("hash"), now) for each in data_list],
        )


async def get_update_time(stocks: list[str], key: KEYS) -> dict[str, NotionDate | None]:
    """
    根据给定的股票列表和键值，从数据库中获取每只股票的更新时间。
    对于空的股票键值，将插入一条值为NULL的记录。

    参数:
        stocks (list[str]): 股票代码列表，用于查询对应的更新时间。
        key (KEYS): 键值，用于筛选特定类型的更新记录。

    返回:
        dict[str, NotionDate | None]: 字典，键为股票代码，值为对应的更新时间（NotionDate类型），
                                      如果未找到记录则返回None。
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
            await conn.executemany(
                "INSERT INTO update_records (stock, key, update_time) VALUES (?, ?, NULL)",
                tuple((stock, key) for stock in missing_stocks),
            )
            for stock in missing_stocks:
                result_dict[stock] = None

        return result_dict


async def set_update_time(
    stock: str, key: KEYS, update_time: NotionDate | None
) -> None:
    """
    更新指定股票和键的更新时间记录。

    参数:
        stock (str): 股票标识符，用于定位需要更新的记录。
        key (KEYS): 键值，与股票一起唯一确定一条记录。
        update_time (NotionDate | None): 新的更新时间，可以为None表示不设置具体时间。

    返回:
        None: 该函数不返回任何值。

    异常:
        ValueError: 如果未找到对应的记录，则抛出此异常，提示业务逻辑错误。
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


__all__ = ["get_conn", "get_update_time", "set_update_time", "check_hash", "save_hash"]
