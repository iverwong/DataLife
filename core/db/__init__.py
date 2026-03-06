"""数据库层公开 API。

重新导出 engine、models 和 repository 函数。
所有存储操作通过 get_session() 获取 session 执行 ORM 操作。
"""
from __future__ import annotations

from dataclasses import dataclass

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
    raise NotImplementedError


async def save_hash(data_list: list[str]) -> None:
    """将哈希值批量保存到数据库中。

    使用 session.add_all() 批量插入 HashRecord。

    Args:
        data_list: 待保存的哈希值字符串列表。
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
