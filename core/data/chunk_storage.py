"""分块结果本地持久化模块。

将 ChunkList 持久化到本地存储：
- 元信息 → SQLite（章节列表、页码映射、分块索引、摘要文本）
- Markdown 分段文件 → 文件系统，按 {stock_code}/{report_date}/{chapter_index}.md 组织

职责边界：
- 只负责存储和读取分块结果
- 不负责分块逻辑
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from core.data.models import Chunk, ChunkList, ChunkType


# ── 常量 ──────────────────────────────────────────────────────────────
DEFAULT_STORAGE_DIR: Path = Path("data/chunks")
"""默认的 Markdown 分段存储根目录。"""


async def init_chunk_tables(db_path: str | None = None) -> None:
    """初始化分块存储所需的 SQLite 表结构。

    仅创建 chunk_meta（分块元信息）表。
    摘要存储表（chunk_summaries）属于 Step 3 的职责，不在此处创建。

    Args:
        db_path: 数据库路径，None 时使用项目默认路径。
    """
    ...


async def save_chunks(
    chunk_list: ChunkList,
    *,
    stock_code: str,
    report_date: str,
    storage_dir: Path = DEFAULT_STORAGE_DIR,
    db_path: str | None = None,
) -> None:
    """将 ChunkList 持久化到本地存储。

    同时写入：
    1. SQLite 元信息（chunk_meta 表）
    2. 文件系统 Markdown 分段（按 stock_code/report_date/chunk_index.md）

    Args:
        chunk_list: 分块结果。
        stock_code: 股票代码。
        report_date: 报告日期（如 "2024-annual"）。
        storage_dir: Markdown 分段存储根目录。
        db_path: 数据库路径。

    Raises:
        IOError: 文件系统写入失败。
    """
    ...


async def load_chunks(
    stock_code: str,
    report_date: str,
    *,
    storage_dir: Path = DEFAULT_STORAGE_DIR,
    db_path: str | None = None,
) -> ChunkList | None:
    """从本地存储加载 ChunkList。

    Args:
        stock_code: 股票代码。
        report_date: 报告日期。
        storage_dir: Markdown 分段存储根目录。
        db_path: 数据库路径。

    Returns:
        ChunkList 对象，未找到时返回 None。
    """
    ...
