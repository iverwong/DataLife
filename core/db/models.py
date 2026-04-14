"""SQLAlchemy 2.0 ORM 模型定义。

所有数据库表结构的单一事实来源（Single Source of Truth）。
"""

from sqlalchemy import String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


class UpdateRecord(Base):
    """更新时间追踪记录。

    复合主键 (stock, key)，记录每只股票各业务键的最近更新时间。
    """
    __tablename__: str = "update_records"

    stock: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    update_time: Mapped[str | None] = mapped_column(Text, nullable=True)


class HashRecord(Base):
    """内容去重哈希记录。

    基于 xxhash 的内容指纹，用于增量更新时跳过已处理数据。
    """
    __tablename__: str = "hash"

    hash: Mapped[str] = mapped_column(Text, primary_key=True)
    create_at: Mapped[str] = mapped_column(Text, nullable=False)
