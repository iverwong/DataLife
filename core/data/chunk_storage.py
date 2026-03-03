"""分块结果本地持久化模块。

将 ChunkList 持久化到本地存储：
- 元信息 → SQLite（章节列表、页码映射、分块索引、摘要文本）
- Markdown 分段文件 → 文件系统，按 {stock_code}/{report_date}/{chapter_index}.md 组织

职责边界：
- 只负责存储和读取分块结果
- 不负责分块逻辑
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import logfire

from core.data.models import Chunk, ChunkList, ChunkMeta, ChunkType


# ── 常量 ──────────────────────────────────────────────────────────────
DEFAULT_STORAGE_DIR: Path = Path("data/chunks")
"""默认的 Markdown 分段存储根目录。"""

# 数据库路径
DEFAULT_DB_PATH: str = "data/chunks.db"


async def init_chunk_tables(db_path: str | None = None) -> None:
    """初始化分块存储所需的 SQLite 表结构。

    仅创建 chunk_meta（分块元信息）表。
    摘要存储表（chunk_summaries）属于 Step 3 的职责，不在此处创建。

    Args:
        db_path: 数据库路径，None 时使用项目默认路径。
    """
    path = db_path or DEFAULT_DB_PATH
    # 确保目录存在
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chunk_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                report_date TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chapter_title TEXT,
                chapter_path TEXT,
                contained_chapters TEXT,
                page_start INTEGER NOT NULL,
                page_end INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                chunk_type TEXT NOT NULL,
                needs_prior_summary INTEGER NOT NULL,
                md_file_path TEXT NOT NULL
            )
        """)
        await db.commit()

    logfire.debug("分块元信息表初始化完成: {db_path}", db_path=path)


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
    db_path = db_path or DEFAULT_DB_PATH
    storage_dir = Path(storage_dir)

    # 确保存储目录存在
    chunk_dir = storage_dir / stock_code / report_date
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # 保存 Markdown 文件并准备元数据
    # tuple elements: (stock_code, report_date, chunk_index, chapter_title, chapter_path_json, contained_chapters_json, page_start, page_end, token_count, chunk_type, needs_prior_summary, md_file_path)
    meta_records: list[tuple[str, str, int, str, str, str, int, int, int, str, int, str]] = []

    for i, chunk in enumerate(chunk_list.chunks):
        # 保存 Markdown 文件（使用序号 i 作为文件名，因为 chunk_index 可能重复）
        md_file_path = chunk_dir / f"{i}.md"
        md_file_path.write_text(chunk.text, encoding="utf-8")

        # 准备元数据记录
        chapter_path_json = json.dumps(chunk.chapter_path, ensure_ascii=False)
        # 序列化 contained_chapters 为 JSON 列表
        contained_chapters_json = json.dumps(
            [
                {
                    "title": cm.title,
                    "level": cm.level,
                    "page_range": cm.page_range,
                }
                for cm in chunk.contained_chapters
            ],
            ensure_ascii=False,
        )
        meta_records.append((
            stock_code,
            report_date,
            chunk.chunk_index,
            chunk.chapter_path[0] if chunk.chapter_path else "",
            chapter_path_json,
            contained_chapters_json,
            chunk.page_range[0],
            chunk.page_range[1],
            chunk.token_count,
            chunk.chunk_type.value,
            1 if chunk.needs_prior_summary else 0,
            str(md_file_path),
        ))

    # 写入 SQLite
    await init_chunk_tables(db_path)

    async with aiosqlite.connect(db_path) as db:
        # 先删除已有的相同 stock_code + report_date 的记录
        await db.execute(
            "DELETE FROM chunk_meta WHERE stock_code = ? AND report_date = ?",
            (stock_code, report_date),
        )

        # 批量插入新记录
        await db.executemany(
            """INSERT INTO chunk_meta
               (stock_code, report_date, chunk_index, chapter_title, chapter_path,
                contained_chapters, page_start, page_end, token_count, chunk_type, needs_prior_summary, md_file_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            meta_records,
        )
        await db.commit()

    logfire.info(
        "分块结果已持久化: stock={stock_code}, date={report_date}, chunks={chunk_count}",
        stock_code=stock_code,
        report_date=report_date,
        chunk_count=len(chunk_list.chunks),
    )


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
    db_path = db_path or DEFAULT_DB_PATH
    storage_dir = Path(storage_dir)

    # 从 SQLite 查询元信息
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM chunk_meta
                   WHERE stock_code = ? AND report_date = ?
                   ORDER BY page_start""",
                (stock_code, report_date),
            )
            rows = await cursor.fetchall()
    except aiosqlite.OperationalError:
        # 表不存在，返回 None
        return None

    # 重建 ChunkList
    chunks: list[Chunk] = []
    total_tokens = 0

    for row in rows:
        # 读取 Markdown 文件
        md_file_path = Path(row["md_file_path"])
        if not md_file_path.exists():
            logfire.warning("Markdown 文件不存在: {path}", path=md_file_path)
            continue

        text = md_file_path.read_text(encoding="utf-8")
        chapter_path = json.loads(row["chapter_path"]) if row["chapter_path"] else []
        chunk_type = ChunkType(row["chunk_type"])

        # 反序列化 contained_chapters
        contained_chapters: list[ChunkMeta] = []
        if row["contained_chapters"]:
            try:
                contained_data = json.loads(row["contained_chapters"])
                contained_chapters = [
                    ChunkMeta(
                        title=item["title"],
                        level=item["level"],
                        page_range=tuple(item["page_range"]),
                    )
                    for item in contained_data
                ]
            except (json.JSONDecodeError, KeyError) as e:
                logfire.warning("contained_chapters 反序列化失败: {error}", error=e)

        chunk = Chunk(
            text=text,
            chapter_path=chapter_path,
            page_range=(row["page_start"], row["page_end"]),
            token_count=row["token_count"],
            chunk_type=chunk_type,
            needs_prior_summary=bool(row["needs_prior_summary"]),
            chunk_index=row["chunk_index"],
            contained_chapters=contained_chapters,
        )
        chunks.append(chunk)
        total_tokens += row["token_count"]

    if not chunks:
        return None

    # 构造 source 标识
    source = f"{stock_code}/{report_date}"

    # 计算章节数（按 level=1 的唯一 chapter_path 数量）
    chapter_count = len({c.chapter_path[0] for c in chunks if c.chapter_path})

    return ChunkList(
        source=source,
        chunks=chunks,
        total_tokens=total_tokens,
        chapter_count=chapter_count,
    )
