# 执行计划：SQLAlchemy 2.0 ORM 数据库层改造

## 1. 目标概述

将 DataLife 项目现有的三个 aiosqlite 直接操作数据库（`notion.db`、`chunks.db`、`datalife.db`）统一迁移到 **SQLAlchemy 2.0 ORM 异步模式**，合并为单一 `data/datalife.db`，覆盖全部 6 张表的 CRUD 操作。

---

## 2. 前置条件

- 当前 `master` 分支代码可正常运行全量测试
- Python 3.13 环境，venv 已激活
- 现有三个 .db 文件中的历史数据**直接丢弃**，不做迁移

---

## 3. 影响范围

### 需重写的文件

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `core/db/__init__.py` | 重写 | 全局 aiosqlite 连接 → 重新导出 engine/models/repository |
| `core/data/chunk_storage.py` | 重写 | 手写 SQL → ORM session 操作 |
| `core/data/summary_storage.py` | 重写 | 手写 SQL → ORM session 操作 |

### 新增文件

| 文件 | 说明 |
| --- | --- |
| `core/db/engine.py` | Engine + async_sessionmaker + get_session() + init_db() + dispose_engine() |
| `core/db/models.py` | Base + 6 个 ORM Record 类 |

### 需重写的测试文件

| 文件 | 说明 |
| --- | --- |
| `tests/conftest.py` | patch `_get_db` → 测试用 AsyncEngine(:memory:  • StaticPool) + session fixture |
| `tests/test_chunk_storage.py` | 调整函数签名，使用 session fixture |
| `tests/test_summary_storage.py` | 同上 |

### 新增测试文件

| 文件 | 说明 |
| --- | --- |
| `tests/test_db.py` | 覆盖 `core/db/__init__.py` 的 4 个 Repository 函数（check_hash、save_hash、get_update_time、set_update_time） |

### 需调整的测试文件

| 文件 | 说明 |
| --- | --- |
| `tests/test_resource_cleanup.py` | `close_db()` → `dispose_engine()` |

### 需同步更新的调用方

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `core/data/chunk_pipeline.py` | 调整 | 移除 `init_chunk_tables()` 调用、移除 `db_path=` 参数 |
| `core/data/summary_pipeline.py` | 调整 | 移除 `init_summary_tables()` 调用、移除 `db_path=` 参数 |
| `main.py` | 调整 | 确认 `init_db()` 调用路径正确（无需传 `db_path`） |

### 不受影响的文件

`test_chapter_detector.py`、`test_chapter_merger.py`、`test_chunker.py`、`test_summary_models.py`、`test_token_counter.py`、`test_business_data_handler.py`、`test_chunk_summarizer.py`、`test_summary_pipeline.py`

---

## ▶ 阶段 A：`/tdd-red` 执行以下步骤

### 步骤 1（串行）：Git 准备

- 操作类型：运行命令
- `depends_on: none`

```bash
git checkout main && git pull origin main && git checkout -b feat/sqlalchemy-orm-migration
```

---

### 步骤 2（串行）：契约定义 — ORM 模型层

- 操作类型：创建文件 `core/db/models.py`
- `depends_on: [1]`

**完整代码**，包含以下 ORM 模型定义：

```python
"""SQLAlchemy 2.0 ORM 模型定义。

所有数据库表结构的单一事实来源（Single Source of Truth）。
合并原 notion.db、chunks.db、datalife.db 为统一 data/datalife.db。
"""
from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

class Base(AsyncAttrs, DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass

# ── 原 notion.db 表 ──────────────────────────────────────────

class UpdateRecord(Base):
    """更新时间追踪记录。

    复合主键 (stock, key)，记录每只股票各业务键的最近更新时间。
    """
    __tablename__ = "update_records"

    stock: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    update_time: Mapped[str | None] = mapped_column(Text, nullable=True)

class HashRecord(Base):
    """内容去重哈希记录。

    基于 xxhash 的内容指纹，用于增量更新时跳过已处理数据。
    """
    __tablename__ = "hash"

    hash: Mapped[str] = mapped_column(Text, primary_key=True)
    create_at: Mapped[str] = mapped_column(Text, nullable=False)

# ── 原 chunks.db 表 ──────────────────────────────────────────

class ChunkMetaRecord(Base):
    """分块元信息持久化记录。

    每条记录对应一个逻辑分块（Chunk），存储章节、页码、token 数等元数据。
    Markdown 文本存储于文件系统，通过 md_file_path 关联。
    """
    __tablename__ = "chunk_meta"
    __table_args__ = (
        Index("ix_chunk_meta_stock_date", "stock_code", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    report_date: Mapped[str] = mapped_column(String, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_title: Mapped[str | None] = mapped_column(Text)
    chapter_path: Mapped[str | None] = mapped_column(Text)
    contained_chapters: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(Text, nullable=False)
    needs_prior_summary: Mapped[int] = mapped_column(Integer, nullable=False)
    md_file_path: Mapped[str] = mapped_column(Text, nullable=False)

    # relationship：级联删除关联的摘要
    summaries: Mapped[list["ChunkSummaryRecord"]] = relationship(
        back_populates="chunk_meta", cascade="all, delete-orphan"
    )

# ── 原 datalife.db 表 ────────────────────────────────────────

class ChunkSummaryRecord(Base):
    """单 Chunk 摘要结果。

    外键关联 chunk_meta.id，存储 LLM 产出的结构化摘要。
    """
    __tablename__ = "chunk_summary"
    __table_args__ = (
        Index("ix_chunk_summary_meta_id", "chunk_meta_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_meta_id: Mapped[int] = mapped_column(ForeignKey("chunk_meta.id", ondelete="CASCADE"), nullable=False)
    chapter_title: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_path: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[str] = mapped_column(Text, nullable=False)
    detailed_summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_data: Mapped[str | None] = mapped_column(Text)
    context_brief: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    chunk_meta: Mapped["ChunkMetaRecord"] = relationship(back_populates="summaries")

class ChapterSummaryRecord(Base):
    """章节级摘要结果。

    合并后或单 Chunk 直出的章节摘要，按 (stock_code, report_date) 查询。
    """
    __tablename__ = "chapter_summary"
    __table_args__ = (
        Index("ix_chapter_summary_stock_date", "stock_code", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    report_date: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_title: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_path: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

class DocumentSummaryRecord(Base):
    """文档级摘要元信息。

    UNIQUE(stock_code, report_date) 确保每份报告只有一条文档摘要。
    """
    __tablename__ = "document_summary"
    __table_args__ = (
        UniqueConstraint("stock_code", "report_date", name="uq_doc_summary_stock_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    report_date: Mapped[str] = mapped_column(Text, nullable=False)
    total_chapters: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    all_key_points: Mapped[str] = mapped_column(Text, nullable=False)
    all_key_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
```

---

### 步骤 3（串行）：契约定义 — Engine 层

- 操作类型：创建文件 `core/db/engine.py`
- `depends_on: [2]`

**完整代码**：

```python
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
    def _enable_foreign_keys(dbapi_connection, connection_record):
        """启用 SQLite 外键约束（默认关闭）。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False
        )
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
```

---

### 步骤 4（串行）：契约定义 — Repository 函数签名

- 操作类型：修改文件 `core/db/__init__.py`
- `depends_on: [3]`

将 `core/db/__init__.py` **完全重写**为导出层，所有函数体使用 `raise NotImplementedError`：

```python
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
```

---

### 步骤 5（串行）：契约定义 — chunk_storage 函数签名

- 操作类型：重写文件 `core/data/chunk_storage.py`
- `depends_on: [4]`

保留原有公开接口签名，函数体全部改为 `raise NotImplementedError`。关键变更：

- 移除 `db_path` 参数（改用全局 `get_session()`）
- `save_chunks` 和 `load_chunks` 签名不变（仍接收 `stock_code`、`report_date`、`storage_dir`），内部改用 ORM session
- `init_chunk_tables` 函数删除（由 `init_db()` 统一替代）

```python
"""分块结果本地持久化模块。

将 ChunkList 持久化到本地存储：
- 元信息 → SQLAlchemy ORM（ChunkMetaRecord）
- Markdown 分段文件 → 文件系统

职责边界：
- 只负责存储和读取分块结果
- 不负责分块逻辑
"""
from __future__ import annotations

from pathlib import Path

from core.data.models import ChunkList

DEFAULT_STORAGE_DIR: Path = Path("data/chunks")
"""默认的 Markdown 分段存储根目录。"""

async def save_chunks(
    chunk_list: ChunkList,
    *,
    stock_code: str,
    report_date: str,
    storage_dir: Path = DEFAULT_STORAGE_DIR,
) -> None:
    """将 ChunkList 持久化到本地存储。

    同时写入：
    1. SQLite ORM 元信息（ChunkMetaRecord，通过 get_session()）
    2. 文件系统 Markdown 分段（按 stock_code/report_date/chunk_index.md）

    流程：
    1. 确保存储目录存在
    2. 写入 Markdown 文件并准备 ORM 对象列表
    3. 通过 get_session() 获取 session
    4. 先删除已有的相同 (stock_code, report_date) 记录
    5. 批量 add 新记录
    6. session 自动 commit

    Args:
        chunk_list: 分块结果。
        stock_code: 股票代码。
        report_date: 报告日期（如 "2024-annual"）。
        storage_dir: Markdown 分段存储根目录。

    Raises:
        IOError: 文件系统写入失败。
    """
    raise NotImplementedError

async def load_chunks(
    stock_code: str,
    report_date: str,
    *,
    storage_dir: Path = DEFAULT_STORAGE_DIR,
) -> ChunkList | None:
    """从本地存储加载 ChunkList。

    流程：
    1. 通过 get_session() 查询 ChunkMetaRecord
    2. 使用 select().where().order_by() 按 page_start 排序
    3. 逐条读取对应的 Markdown 文件
    4. 重建 ChunkList 对象

    Args:
        stock_code: 股票代码。
        report_date: 报告日期。
        storage_dir: Markdown 分段存储根目录。

    Returns:
        ChunkList 对象，未找到时返回 None。
    """
    raise NotImplementedError
```

---

### 步骤 6（串行）：契约定义 — summary_storage 函数签名

- 操作类型：重写文件 `core/data/summary_storage.py`
- `depends_on: [5]`

保留原有公开接口签名，函数体全部改为 `raise NotImplementedError`。关键变更：

- 移除所有 `db_path` 参数
- `init_summary_tables` 函数删除（由 `init_db()` 统一替代）
- `save_document_summary` 中的 `INSERT OR REPLACE`（SQLite 特有）改为 `session.merge()` 语义，在 docstring 中明确说明

```python
"""摘要结果 SQLAlchemy ORM 持久化模块。

与 Step 2 的 chunk_meta 表关联，存储摘要输出。
所有操作通过 get_session() 获取 session 执行。
"""
from __future__ import annotations

from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
)

async def save_chunk_summary(
    chunk_meta_id: int,
    summary: ChunkSummaryOutput,
) -> int:
    """保存单个 Chunk 的摘要结果。

    将 ChunkSummaryOutput 转为 ChunkSummaryRecord 并 add 到 session。
    JSON 序列化字段（key_points, chapter_path, key_data）使用 json.dumps。

    Args:
        chunk_meta_id: chunk_meta 表中对应的记录 ID。
        summary: Chunk 摘要输出。

    Returns:
        插入记录的 ID。

    Raises:
        SummaryStorageError: 写入失败。
    """
    raise NotImplementedError

async def save_chapter_summary(
    chapter: ChapterSummary,
    stock_code: str,
    report_date: str,
) -> int:
    """保存章节级摘要结果。

    将 ChapterSummary 转为 ChapterSummaryRecord 并 add 到 session。

    Args:
        chapter: 章节摘要。
        stock_code: 股票代码。
        report_date: 报告日期。

    Returns:
        插入记录的 ID。

    Raises:
        SummaryStorageError: 写入失败。
    """
    raise NotImplementedError

async def save_document_summary(
    doc_summary: DocumentSummary,
) -> int:
    """保存完整文档摘要元信息。

    使用先查后更新/插入实现 upsert 语义（替代原 INSERT OR REPLACE），
    先按 (stock_code, report_date) 查询：
    - 已存在 → 更新所有字段
    - 不存在 → 插入新记录

    从 doc_summary.source 字段提取 stock_code 和 report_date（格式: "600000_2024-12-31"）。

    Args:
        doc_summary: 文档级摘要。

    Returns:
        插入/更新记录的 ID。

    Raises:
        SummaryStorageError: 写入失败或 source 格式无效。
    """
    raise NotImplementedError

async def load_document_summary(
    stock_code: str,
    report_date: str,
) -> DocumentSummary | None:
    """按股票代码和报告日期加载文档摘要。

    使用 select().where() 查询 DocumentSummaryRecord，反序列化为 DocumentSummary。
    JSON 字段（all_key_points, all_key_data）使用 json.loads 反序列化。

    Args:
        stock_code: 股票代码。
        report_date: 报告日期。

    Returns:
        DocumentSummary 或 None（未找到）。

    Raises:
        SummaryStorageError: 读取失败。
    """
    raise NotImplementedError
```

---

### 步骤 7（串行）：测试用例 — conftest + 全部测试

- 操作类型：重写测试文件
- `depends_on: [6]`

#### 7a. 重写 `tests/conftest.py`

核心变更：

- 移除 `_test_db_conn` 全局 aiosqlite 连接
- 新增 `test_engine` fixture：`create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False, "autocommit": False})`
- 新增 `init_test_db` fixture：调用 `configure_for_testing(engine)` + `run_sync(Base.metadata.create_all)`
- `pytest_sessionfinish` 中 `close_db()` → `dispose_engine()`

关键测试 fixture 设计：

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from core.db.engine import configure_for_testing, dispose_engine
from core.db.models import Base

@pytest.fixture
async def test_engine():
    """创建 :memory: + StaticPool 的测试引擎。

    StaticPool 确保所有操作共享同一连接（异步模式下 :memory: 的每个连接是独立空数据库）。
    """
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
```

#### 7b. 重写 `tests/test_chunk_storage.py`（6 个测试）

所有测试改为依赖 `test_engine` fixture，调用新签名函数。断言逻辑不变：

- `test_save_and_load_chunks` — 正向 round-trip
- `test_load_nonexistent` — 未找到返回 None
- `test_overwrite_existing` — 同 (stock, date) 覆盖
- `test_contained_chapters_persistence` — contained_chapters JSON round-trip
- `test_multiple_stocks` — 多股票隔离
- `test_empty_chunklist` — 空列表边界

#### 7c. 重写 `tests/test_summary_storage.py`（4 个测试）

外键准备改为 `session.add(ChunkMetaRecord(...))`，调用新签名函数：

- `test_save_and_load_document_summary` — 正向 round-trip
- `test_save_chunk_summary` — 插入返回 ID
- `test_save_chapter_summary` — 插入返回 ID
- `test_document_summary_upsert` — 先查后更新 upsert 验证

#### 7d. 调整 `tests/test_resource_cleanup.py`

- `close_db()` → `dispose_engine()`
- 幂等性测试目标调整

#### 7e. 新建 `tests/test_db.py`（5 个测试）

覆盖 `core/db/__init__.py` 的 4 个 Repository 函数，所有测试依赖 `test_engine` fixture：

- `test_check_hash_filters_existing` — 插入已有哈希后调用 check_hash，验证仅返回不存在的项
- `test_save_hash_persists` — save_hash 后查询 HashRecord 验证持久化
- `test_get_update_time_inserts_missing` — 对缺失股票调用 get_update_time，验证自动插入 NULL 行并返回 None
- `test_set_update_time_updates_existing` — 先 get_update_time 插入行，再 set_update_time 更新，验证值变更
- `test_set_update_time_raises_on_missing` — 对不存在的记录调用 set_update_time，验证抛出 ValueError

---

### 步骤 8（串行）：静态检查与验证全红

- 操作类型：运行命令
- `depends_on: [7]`

```bash
# 类型检查
basedpyright core/db/ core/data/chunk_storage.py core/data/summary_storage.py

# Linter
ruff check core/db/ core/data/chunk_storage.py core/data/summary_storage.py

# 运行测试 — 确认全部失败且失败原因均为 NotImplementedError
pytest tests/test_chunk_storage.py tests/test_summary_storage.py tests/test_resource_cleanup.py tests/test_db.py --tb=short -v

# 验证：检查所有失败的 traceback 中是否均为 NotImplementedError
```

---

### 步骤 9（串行）：Git 提交 Red 阶段

- 操作类型：运行命令
- `depends_on: [8]`

```bash
git add -A
git commit -m "test: add SQLAlchemy ORM contracts and failing tests for db migration"
```

---

## ▶ 阶段 B：`/tdd-green` 执行以下步骤

<aside>
⚠️

**阶段 B 前置检查**：确认契约文件中所有 stub 均为 `raise NotImplementedError`，不存在重复定义或残留的旧实现，避免新实现被 stub 覆盖。

</aside>

---

### 6. 核心实现参考

<aside>
📖

以下代码示例均来源于 **SQLAlchemy 2.0 官方文档**（[https://docs.sqlalchemy.org/en/20/）和项目现有代码风格。](https://docs.sqlalchemy.org/en/20/）和项目现有代码风格。)

</aside>

#### 6.1 异步引擎与会话（来源：SQLAlchemy 2.0 Async Extension）

```python
# 创建异步引擎
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine("sqlite+aiosqlite:///data/datalife.db", echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# 使用会话
async with SessionLocal() as session:
    result = await session.execute(select(MyModel).where(MyModel.id == 1))
    obj = result.scalar_one_or_none()
```

#### 6.2 声明式 ORM 模型（来源：SQLAlchemy 2.0 Mapped Column）

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
```

#### 6.3 异步建表（来源：SQLAlchemy 2.0 run_sync）

```python
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
```

#### 6.4 ORM 查询（来源：SQLAlchemy 2.0 select）

```python
from sqlalchemy import select, delete

# 查询
result = await session.execute(
    select(ChunkMetaRecord)
    .where(ChunkMetaRecord.stock_code == stock_code)
    .where(ChunkMetaRecord.report_date == report_date)
    .order_by(ChunkMetaRecord.page_start)
)
rows = result.scalars().all()

# 删除
await session.execute(
    delete(ChunkMetaRecord)
    .where(ChunkMetaRecord.stock_code == stock_code)
    .where(ChunkMetaRecord.report_date == report_date)
)

# 批量插入
session.add_all([record1, record2, record3])
```

#### 6.5 Relationship 与 selectinload（来源：SQLAlchemy 2.0 Relationship Loading）

```python
from sqlalchemy.orm import selectinload

# 避免异步模式下 lazy loading 异常
result = await session.execute(
    select(ChunkMetaRecord)
    .options(selectinload(ChunkMetaRecord.summaries))
    .where(ChunkMetaRecord.id == meta_id)
)
```

#### 6.6 Upsert 语义 — 先查后更新/插入（来源：SQLAlchemy 2.0 Session.merge）

```python
# 替代 INSERT OR REPLACE（SQLite 特有语法）
# merge() 根据主键判断：存在则更新，不存在则插入
existing = await session.execute(
    select(DocumentSummaryRecord)
    .where(DocumentSummaryRecord.stock_code == stock_code)
    .where(DocumentSummaryRecord.report_date == report_date)
)
record = existing.scalar_one_or_none()
if record is not None:
    # 更新已有记录的字段
    record.total_chapters = doc_summary.total_chapters
    # ... 更新其余字段
else:
    record = DocumentSummaryRecord(...)
    session.add(record)
```

#### 6.7 测试：:memory: + StaticPool（来源：SQLAlchemy 2.0 Testing）

```python
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine

# 异步模式下 :memory: SQLite 必须配合 StaticPool
# 确保所有操作共享同一连接（否则每个连接是独立的空数据库）
engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False, "autocommit": False},
)
```

#### 6.8 xxhash 计算（保留现有用法）

```python
import json
import xxhash

content = json.dumps({"data_type": item.data_type, "content": item.content}, sort_keys=True, ensure_ascii=False)
hash_value = xxhash.xxh3_64_hexdigest(content.encode())
```

---

### 7. 实现步骤

#### 步骤 10（并发 Sub-agent A）：实现 core/db/**init**.py 中的 Repository 函数

- 操作类型：修改文件 `core/db/__init__.py`
- `depends_on: [9]`

实现 4 个函数：

1. **`check_hash`**：计算 xxhash → 批量 select 查已存在 → 过滤返回。参考 6.4 + 6.8
2. **`save_hash`**：构建 HashRecord 列表 → session.add_all()。参考 6.4
3. **`get_update_time`**：select 查询 → 对缺失股票 session.add 插入 NULL 行 → 返回字典。参考 6.4
4. **`set_update_time`**：select 查询 → 更新属性 → 未找到 raise ValueError。参考 6.4

验证：`pytest tests/ -k "test_resource_cleanup or test_db" --tb=short -v`

Git 提交：`feat: implement db repository functions with SQLAlchemy ORM`

---

#### 步骤 11（并发 Sub-agent B）：实现 core/data/chunk_[storage.py](http://storage.py)

- 操作类型：修改文件 `core/data/chunk_storage.py`
- `depends_on: [9]`

实现 2 个函数：

1. **`save_chunks`**：遍历 chunk_list → 写 Markdown 文件 + 构建 ChunkMetaRecord 列表 → get_session() 内先 delete 后 add_all。JSON 序列化 chapter_path/contained_chapters 与现有逻辑一致。参考 6.4
2. **`load_chunks`**：get_session() 内 select + order_by → 读 Markdown 文件 → 重建 Chunk 列表 → 构造 ChunkList。反序列化 contained_chapters 为 ChunkMeta 列表，与现有逻辑一致。捕获 `NoResultFound` 等异常返回 None。参考 6.4

验证：`pytest tests/test_chunk_storage.py --tb=short -v`

Git 提交：`feat: implement chunk_storage with SQLAlchemy ORM`

---

#### 步骤 12（并发 Sub-agent C）：实现 core/data/summary_[storage.py](http://storage.py)

- 操作类型：修改文件 `core/data/summary_storage.py`
- `depends_on: [9]`

实现 4 个函数：

1. **`save_chunk_summary`**：构建 ChunkSummaryRecord → session.add → flush 取 id。JSON 序列化 key_points/chapter_path/key_data。参考 6.4
2. **`save_chapter_summary`**：构建 ChapterSummaryRecord → session.add → flush 取 id。参考 6.4
3. **`save_document_summary`**：从 source 解析 stock_code/report_date → 先查询已有记录 → 存在则更新/不存在则 add。参考 6.6
4. **`load_document_summary`**：select 查询 → 反序列化 JSON 字段 → 构建 DocumentSummary。参考 6.4

验证：`pytest tests/test_summary_storage.py --tb=short -v`

Git 提交：`feat: implement summary_storage with SQLAlchemy ORM`

---

#### 步骤 12a（串行）：更新调用方文件

- 操作类型：修改文件 `core/data/chunk_pipeline.py`、`core/data/summary_pipeline.py`、`main.py`
- `depends_on: [10, 11, 12]`

根据第 3 节"需同步更新的调用方"表格，逐文件调整：

1. **`core/data/chunk_pipeline.py`**：移除 `init_chunk_tables()` 调用、移除所有 `db_path=` 参数传递
2. **`core/data/summary_pipeline.py`**：移除 `init_summary_tables()` 调用、移除所有 `db_path=` 参数传递
3. **`main.py`**：确认 `init_db()` 调用路径正确（无需传 `db_path`），启动时调用 `init_db()` 替代原有分散建表逻辑

验证：

```bash
# 静态检查调用方
basedpyright core/data/chunk_pipeline.py core/data/summary_pipeline.py main.py

# 确认无残留旧 API 调用
grep -rn "init_chunk_tables\|init_summary_tables\|db_path" core/data/chunk_pipeline.py core/data/summary_pipeline.py main.py
# 预期：无输出
```

Git 提交：`refactor: update caller files to use new ORM API`

---

### 并发执行依赖图

```jsx
步骤 1（串行）：git checkout -b feat/sqlalchemy-orm-migration
步骤 2-6（串行）：契约定义（models → engine → __init__ → chunk_storage → summary_storage）
步骤 7（串行）：测试用例
步骤 8（串行）：验证全红
步骤 9（串行）：git commit "test: add contracts and failing tests"
阶段 B（并发）：
    ├─ Sub-agent A：步骤 10 实现 db repository → 运行测试 → git commit
    ├─ Sub-agent B：步骤 11 实现 chunk_storage → 运行测试 → git commit
    └─ Sub-agent C：步骤 12 实现 summary_storage → 运行测试 → git commit
步骤 12a（串行）：更新调用方文件（chunk_pipeline / summary_pipeline / main）→ git commit
步骤 13（串行）：全量验证 + 最终提交
```

---

### 步骤 13（串行）：验证清单

- 操作类型：运行命令
- `depends_on: [12a]`

```bash
# 全量测试
pytest tests/ -v

# 类型检查
basedpyright core/

# Linter
ruff check core/

# 确认无残留 aiosqlite 直接调用（除 engine 层的驱动依赖）
grep -rn "aiosqlite.connect" core/ --include="*.py" | grep -v "engine.py" | grep -v "__pycache__"
# 预期：无输出

# 确认无残留手写 SQL
grep -rn "CREATE TABLE" core/ --include="*.py" | grep -v "__pycache__"
# 预期：无输出

# 确认调用方无残留旧 API
grep -rn "init_chunk_tables\|init_summary_tables\|db_path" core/ main.py --include="*.py" | grep -v "engine.py" | grep -v "__pycache__"
# 预期：无输出

# 如有修复则提交
git add -A && git commit -m "fix: resolve integration issues from ORM migration"
```

---

## 8. 测试补充

实现完成后，评估并补充以下测试场景：

1. **外键级联删除**：删除 ChunkMetaRecord 后验证关联的 ChunkSummaryRecord 被级联删除
2. **并发 session 隔离**：两个 get_session() 上下文中的操作互不干扰
3. **dispose_engine 幂等性**：连续调用两次 dispose_engine() 不报错
4. **PRAGMA foreign_keys 验证**：插入违反外键约束的记录确认抛出 IntegrityError

---

## 9. 技术决策说明

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 数据库合并 | 三合一 `data/datalife.db` | 减少连接管理复杂度，简化事务边界 |
| Session 模式 | 模块级 Engine 单例 + get_session() 上下文管理器 | 与项目现有 `get_conn()` 模式一致，迁移成本低 |
| Schema 管理 | `metadata.create_all()` | 开发阶段数据库可随时删除重建，不引入 Alembic 复杂度 |
| Upsert 语义 | 先查后更新/插入（非 merge()） | merge() 依赖主键，而 document_summary 的 upsert 基于 UNIQUE 约束，用显式查询更可控 |
| 测试隔离 | `:memory:`  • StaticPool + `configure_for_testing()` | 异步 :memory: SQLite 需 StaticPool 共享连接；通过注入替换全局引擎实现隔离 |
| 历史数据 | 直接丢弃 | 开发阶段数据量小，重新运行管线生成成本低 |

---

## 10. 依赖变更

```bash
# 安装 SQLAlchemy 异步支持（greenlet 为必需依赖）
pip install "sqlalchemy[asyncio]>=2.0"

# aiosqlite 保留为直接依赖（SQLAlchemy 不自动安装）
# 项目已有 aiosqlite，无需额外安装
```

验证 Python 3.13 兼容性：SQLAlchemy ≥ 2.0.36 支持 Python 3.13。