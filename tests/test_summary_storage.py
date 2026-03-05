"""摘要存储测试。

使用临时 SQLite 数据库，验证表创建和读写。
"""
from __future__ import annotations

import pytest
from pathlib import Path

from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
)
from core.data.summary_storage import (
    init_summary_tables,
    load_document_summary,
    save_chapter_summary,
    save_chunk_summary,
    save_document_summary,
)


# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """临时数据库文件路径。"""
    return tmp_path / "test_summary.db"


@pytest.fixture
def sample_chunk_summary() -> ChunkSummaryOutput:
    return ChunkSummaryOutput(
        chapter_title="第一节",
        chapter_path=["第一节"],
        key_points=["要点1"],
        detailed_summary="详细摘要",
        key_data=[KeyDataItem(label="营收", value=1e9, unit="元")],
        context_brief="上下文",
    )


# ── init_summary_tables ────────────────────────────────
class TestInitSummaryTables:
    @pytest.mark.asyncio
    async def test_creates_tables(self, tmp_db: Path) -> None:
        """首次调用创建所有摘要表。"""
        await init_summary_tables(db_path=tmp_db)
        # 验证表存在（通过 aiosqlite 查询 sqlite_master）
        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        assert "chunk_summary" in tables
        assert "chapter_summary" in tables
        assert "document_summary" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db: Path) -> None:
        """重复调用不报错（IF NOT EXISTS）。"""
        await init_summary_tables(db_path=tmp_db)
        await init_summary_tables(db_path=tmp_db)


# ── save / load ────────────────────────────────────────
class TestSaveAndLoad:
    @pytest.mark.asyncio
    async def test_save_chunk_summary(
        self, tmp_db: Path, sample_chunk_summary: ChunkSummaryOutput
    ) -> None:
        """保存 Chunk 摘要并验证返回 ID。"""
        await init_summary_tables(db_path=tmp_db)
        # 需要先创建 chunk_meta 表和记录以提供外键
        # 此处简化：先创建 chunk_meta 表
        import aiosqlite

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS chunk_meta "
                "(id INTEGER PRIMARY KEY, stock_code TEXT, report_date TEXT)"
            )
            cursor = await db.execute(
                "INSERT INTO chunk_meta (stock_code, report_date) VALUES (?, ?)",
                ("600000", "2024-12-31"),
            )
            chunk_meta_id = cursor.lastrowid
            await db.commit()

        record_id = await save_chunk_summary(
            chunk_meta_id=chunk_meta_id,  # type: ignore[arg-type]
            summary=sample_chunk_summary,
            db_path=tmp_db,
        )
        assert isinstance(record_id, int)
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_save_and_load_document_summary(self, tmp_db: Path) -> None:
        """保存并加载完整文档摘要，验证往返一致性。"""
        await init_summary_tables(db_path=tmp_db)
        doc = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[],
            all_key_points=["全文要点"],
            all_key_data=[KeyDataItem(label="总资产", value=1e10, unit="元")],
            total_chunks_processed=8,
            total_chapters=4,
        )
        await save_document_summary(doc, db_path=tmp_db)
        loaded = await load_document_summary(
            "600000", "2024-12-31", db_path=tmp_db
        )
        assert loaded is not None
        assert loaded.source == "600000_2024-12-31"
        assert loaded.total_chunks_processed == 8
        assert len(loaded.all_key_data) == 1

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_db: Path) -> None:
        """查询不存在的记录返回 None。"""
        await init_summary_tables(db_path=tmp_db)
        result = await load_document_summary(
            "999999", "2099-01-01", db_path=tmp_db
        )
        assert result is None
