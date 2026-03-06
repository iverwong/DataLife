"""数据库层公开 API。

重新导出 engine、models 和 repository 函数。
所有存储操作通过 get_session() 获取 session 执行 ORM 操作。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import xxhash
from sqlalchemy import select

from core.db.engine import (
    configure_for_testing,
    dispose_engine,
    get_engine,
    get_session,
    get_session_factory,
    init_db,
)
from core.db.models import (
    Base,
    ChapterSummaryRecord,
    ChunkMetaRecord,
    ChunkSummaryRecord,
    DocumentSummaryRecord,
    HashRecord,
    UpdateRecord,
)
from core.models import NotionDate, UpdateRecordKey


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


async def check_hash(data_list: list[HashContent]) -> list[HashContentWithHash]:
    """检查数据列表中的哈希值是否已存在于数据库中，返回未存在的数据项。

    流程：
    1. 对每个 HashContent 计算 xxhash 指纹
    2. 批量查询数据库中已存在的哈希
    3. 返回仅包含数据库中尚未存在的数据项（附计算后的哈希值）

    Args:
        data_list: 待检查的哈希内容列表。

    Returns:
        仅包含数据库中尚未存在的数据项（附计算后的哈希值）。
    """
    if not data_list:
        return []

    # 计算每个 item 的哈希值
    hash_contents: list[HashContentWithHash] = []
    for item in data_list:
        content = json.dumps(
            {"data_type": item.data_type, "content": item.content},
            sort_keys=True,
            ensure_ascii=False,
        )
        hash_value = xxhash.xxh3_64_hexdigest(content.encode())
        hash_contents.append(
            HashContentWithHash(
                data_type=item.data_type,
                content=item.content,
                hash_value=hash_value,
            )
        )

    # 批量查询已存在的哈希
    hash_values = [h.hash_value for h in hash_contents]
    async with get_session() as session:
        result = await session.execute(
            select(HashRecord.hash).where(HashRecord.hash.in_(hash_values))
        )
        existing_hashes = {row for row in result.scalars().all()}

    # 过滤出不存在的数据项
    return [h for h in hash_contents if h.hash_value not in existing_hashes]


async def save_hash(data_list: list[str | HashContent]) -> None:
    """将哈希值批量保存到数据库中。

    使用 session.add_all() 批量插入 HashRecord。

    Args:
        data_list: 待保存的哈希内容列表，可以是字符串哈希值或 HashContent 对象。
    """
    if not data_list:
        return

    hash_values: list[str] = []
    for h in data_list:
        if isinstance(h, str):
            hash_values.append(h)
        else:
            # HashContent 对象，计算哈希值
            content = json.dumps(
                {"data_type": h.data_type, "content": h.content},
                sort_keys=True,
                ensure_ascii=False,
            )
            hash_value = xxhash.xxh3_64_hexdigest(content.encode())
            hash_values.append(hash_value)

    records = [
        HashRecord(hash=h, create_at=datetime.now().isoformat())
        for h in hash_values
    ]
    async with get_session() as session:
        session.add_all(records)


async def get_update_time(
    stocks: list[str], key: UpdateRecordKey
) -> dict[str, NotionDate | None]:
    """获取股票列表的更新时间记录，对缺失记录自动插入 NULL 行。

    使用 select() + where() 查询，对缺失股票使用 session.add() 插入。

    Args:
        stocks: 股票代码列表。
        key: 业务键类型。

    Returns:
        字典，键为股票代码，值为对应的更新时间（可能为 None）。
    """
    if not stocks:
        return {}

    async with get_session() as session:
        # 查询已存在的记录
        result = await session.execute(
            select(UpdateRecord).where(
                UpdateRecord.stock.in_(stocks), UpdateRecord.key == key
            )
        )
        existing_records = {r.stock: r.update_time for r in result.scalars().all()}

        # 插入缺失的记录
        missing_stocks = [s for s in stocks if s not in existing_records]
        if missing_stocks:
            new_records = [
                UpdateRecord(stock=s, key=key, update_time=None)
                for s in missing_stocks
            ]
            session.add_all(new_records)

        # 构建返回结果
        result = {s: existing_records.get(s) for s in stocks}
        return cast(dict[str, NotionDate | None], result)


async def set_update_time(
    stock: str, key: UpdateRecordKey, update_time: NotionDate | None
) -> None:
    """更新指定股票和键的更新时间记录。

    使用 select() 查询后 update 属性值，若未找到则 raise ValueError。

    Args:
        stock: 股票代码。
        key: 业务键类型。
        update_time: 新的更新时间，可以为 None。

    Raises:
        ValueError: 如果未找到对应的记录（应先查询后更新）。
    """
    async with get_session() as session:
        result = await session.execute(
            select(UpdateRecord).where(
                UpdateRecord.stock == stock, UpdateRecord.key == key
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            raise ValueError(
                f"UpdateRecord not found for stock={stock}, key={key}"
            )

        record.update_time = update_time


__all__ = [
    # Engine & session
    "get_engine",
    "get_session",
    "get_session_factory",
    "init_db",
    "dispose_engine",
    "configure_for_testing",
    # Models
    "Base",
    "UpdateRecord",
    "HashRecord",
    "ChunkMetaRecord",
    "ChunkSummaryRecord",
    "ChapterSummaryRecord",
    "DocumentSummaryRecord",
    # Data classes
    "HashContent",
    "HashContentWithHash",
    # Repository functions
    "check_hash",
    "save_hash",
    "get_update_time",
    "set_update_time",
]
