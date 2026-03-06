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
