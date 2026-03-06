"""分块结果本地持久化模块。

将 ChunkList 持久化到本地存储：
- 元信息 → SQLAlchemy ORM（ChunkMetaRecord）
- Markdown 分段文件 → 文件系统

职责边界：
- 只负责存储和读取分块结果
- 不负责分块逻辑
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, select

from core.data.models import Chunk, ChunkList, ChunkMeta, ChunkType
from core.db.engine import get_session
from core.db.models import ChunkMetaRecord

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
    1. ORM 元信息（ChunkMetaRecord，通过 get_session()）
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
    # 1. 确保存储目录存在
    stock_dir = storage_dir / stock_code / report_date
    stock_dir.mkdir(parents=True, exist_ok=True)

    # 2. 遍历 chunk_list，写入 Markdown 文件 + 构建 ChunkMetaRecord 列表
    records: list[ChunkMetaRecord] = []

    # 处理空列表情况：写入一条标记记录
    if not chunk_list.chunks:
        record = ChunkMetaRecord(
            stock_code=stock_code,
            report_date=report_date,
            chunk_index=0,
            chapter_title=None,
            chapter_path=None,
            contained_chapters=None,
            page_start=0,
            page_end=0,
            token_count=0,
            chunk_type="",  # 空字符串标记空 ChunkList
            needs_prior_summary=0,
            md_file_path=str(stock_dir / "0.md"),
        )
        records.append(record)
    else:
        for idx, chunk in enumerate(chunk_list.chunks):
            # 写入 Markdown 文件
            md_path = stock_dir / f"{idx}.md"
            _ = md_path.write_text(chunk.text, encoding="utf-8")

            # 构建 ORM 对象
            record = ChunkMetaRecord(
                stock_code=stock_code,
                report_date=report_date,
                chunk_index=idx,
                chapter_title=chunk.chapter_path[-1] if chunk.chapter_path else None,
                chapter_path=json.dumps(chunk.chapter_path, ensure_ascii=False),
                contained_chapters=json.dumps(
                    [c.__dict__ for c in chunk.contained_chapters],
                    ensure_ascii=False,
                )
                if chunk.contained_chapters
                else None,
                page_start=chunk.page_range[0],
                page_end=chunk.page_range[1],
                token_count=chunk.token_count,
                chunk_type=chunk.chunk_type.value,
                needs_prior_summary=1 if chunk.needs_prior_summary else 0,
                md_file_path=str(md_path),
            )
            records.append(record)

    # 3-5. 通过 get_session() 获取 session，删除旧记录，批量添加新记录
    async with get_session() as session:
        # 删除已有的相同 (stock_code, report_date) 记录
        _ = await session.execute(
            delete(ChunkMetaRecord)
            .where(ChunkMetaRecord.stock_code == stock_code)
            .where(ChunkMetaRecord.report_date == report_date)
        )
        # 批量 add 新记录
        session.add_all(records)


async def load_chunks(stock_code: str, report_date: str) -> ChunkList | None:
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
    try:
        async with get_session() as session:
            # 1. 查询 ChunkMetaRecord
            result = await session.execute(
                select(ChunkMetaRecord)
                .where(ChunkMetaRecord.stock_code == stock_code)
                .where(ChunkMetaRecord.report_date == report_date)
                .order_by(ChunkMetaRecord.page_start)
            )
            rows = result.scalars().all()

            if not rows:
                return None

            # 2-3. 逐条读取 Markdown 文件并重建 Chunk 对象
            chunks: list[Chunk] = []

            # 检查是否是空 ChunkList 标记（chunk_type 为空字符串）
            if rows and rows[0].chunk_type == "":
                # 空 ChunkList，直接返回
                return ChunkList(
                    source=f"{stock_code}/{report_date}",
                    chunks=[],
                    total_tokens=0,
                    chapter_count=0,
                )

            for row in rows:
                md_path = Path(row.md_file_path)
                text = md_path.read_text(encoding="utf-8")

                chapter_path: list[str] = (
                    json.loads(row.chapter_path) if row.chapter_path else []
                )

                contained_chapters: list[ChunkMeta] = []
                if row.contained_chapters:
                    for c in json.loads(row.contained_chapters):
                        contained_chapters.append(
                            ChunkMeta(
                                title=c["title"],
                                level=c["level"],
                                page_range=c["page_range"],
                            )
                        )

                chunks.append(
                    Chunk(
                        text=text,
                        chapter_path=chapter_path,
                        page_range=(row.page_start, row.page_end),
                        token_count=row.token_count,
                        chunk_type=ChunkType(row.chunk_type),
                        needs_prior_summary=bool(row.needs_prior_summary),
                        chunk_index=row.chunk_index,
                        contained_chapters=contained_chapters,
                    )
                )

            # 4. 重建 ChunkList 对象
            return ChunkList(
                source=f"{stock_code}/{report_date}",
                chunks=chunks,
                total_tokens=sum(c.token_count for c in chunks),
                chapter_count=len(chunks),
            )
    except Exception:
        # 捕获异常返回 None
        return None
