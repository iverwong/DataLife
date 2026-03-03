"""分块持久化模块测试。"""
from __future__ import annotations

import pytest
from pathlib import Path

from core.data.models import Chunk, ChunkList, ChunkType
from core.data.chunk_storage import init_chunk_tables, save_chunks, load_chunks


@pytest.fixture
def sample_chunk_list() -> ChunkList:
    """构造测试用 ChunkList。"""
    chunks = [
        Chunk(
            text="# 第一章\n正文内容",
            chapter_path=["第一章"],
            page_range=(1, 3),
            token_count=100,
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            needs_prior_summary=False,
            chunk_index=0,
        ),
        Chunk(
            text="# 第二章\n更多内容",
            chapter_path=["第二章"],
            page_range=(4, 8),
            token_count=200,
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            needs_prior_summary=True,
            chunk_index=0,
        ),
    ]
    return ChunkList(source="test", chunks=chunks, total_tokens=300, chapter_count=2)


class TestChunkStorage:
    """分块存储测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, sample_chunk_list, tmp_path):
        """保存后加载应还原相同的 ChunkList。"""
        db_path = str(tmp_path / "test.db")
        storage_dir = tmp_path / "chunks"
        await init_chunk_tables(db_path=db_path)
        await save_chunks(
            sample_chunk_list,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
            db_path=db_path,
        )
        loaded = await load_chunks(
            "300274", "2024-annual",
            storage_dir=storage_dir,
            db_path=db_path,
        )
        assert loaded is not None
        assert len(loaded.chunks) == 2
        assert loaded.chunks[0].text == sample_chunk_list.chunks[0].text
        assert loaded.total_tokens == 300

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        """加载不存在的记录应返回 None。"""
        db_path = str(tmp_path / "test.db")
        await init_chunk_tables(db_path=db_path)
        result = await load_chunks(
            "999999", "2099-annual",
            storage_dir=tmp_path / "chunks",
            db_path=db_path,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_markdown_files_created(self, sample_chunk_list, tmp_path):
        """保存后应在文件系统创建 Markdown 分段文件。"""
        db_path = str(tmp_path / "test.db")
        storage_dir = tmp_path / "chunks"
        await init_chunk_tables(db_path=db_path)
        await save_chunks(
            sample_chunk_list,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
            db_path=db_path,
        )
        chunk_dir = storage_dir / "300274" / "2024-annual"
        assert chunk_dir.exists()
        md_files = list(chunk_dir.glob("*.md"))
        assert len(md_files) == 2
