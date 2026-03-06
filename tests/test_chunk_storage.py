"""分块持久化模块测试。"""
from __future__ import annotations

import pytest

from core.data.models import Chunk, ChunkList, ChunkType
from core.data.chunk_storage import save_chunks, load_chunks


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
            contained_chapters=[],
        ),
        Chunk(
            text="# 第二章\n更多内容",
            chapter_path=["第二章"],
            page_range=(4, 8),
            token_count=200,
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            needs_prior_summary=True,
            chunk_index=0,
            contained_chapters=[],
        ),
    ]
    return ChunkList(source="test", chunks=chunks, total_tokens=300, chapter_count=2)


@pytest.fixture
def chunk_with_contained_chapters() -> ChunkList:
    """构造包含 contained_chapters 信息的 ChunkList（T3/T4 验证用）。"""
    from core.data.models import ChunkMeta

    chunks = [
        Chunk(
            text="# 合并章\n正文",
            chapter_path=["合并章"],
            page_range=(1, 1),
            token_count=50,
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            needs_prior_summary=False,
            chunk_index=0,
            contained_chapters=[
                ChunkMeta(title="第一节", level=1, page_range=(1, 1)),
                ChunkMeta(title="第二节", level=1, page_range=(1, 1)),
            ],
        ),
    ]
    return ChunkList(source="contained_test.pdf", chunks=chunks, total_tokens=50, chapter_count=2)


class TestChunkStorage:
    """分块存储测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_chunks(self, test_engine, sample_chunk_list, tmp_path):
        """保存后加载应还原相同的 ChunkList。"""
        storage_dir = tmp_path / "chunks"
        await save_chunks(
            sample_chunk_list,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )
        loaded = await load_chunks(
            "300274", "2024-annual",
        )
        assert loaded is not None
        assert len(loaded.chunks) == 2
        assert loaded.chunks[0].text == sample_chunk_list.chunks[0].text
        assert loaded.total_tokens == 300

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, test_engine, tmp_path):
        """加载不存在的记录应返回 None。"""
        result = await load_chunks(
            "999999", "2099-annual",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_existing(self, test_engine, sample_chunk_list, tmp_path):
        """覆盖写入（同一 stock_code + report_date 保存两次）应幂等，第二次覆盖第一次。"""
        storage_dir = tmp_path / "chunks"

        # 第一次保存
        await save_chunks(
            sample_chunk_list,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )

        # 第二次保存（不同内容）
        chunks_v2 = [
            Chunk(
                text="# 新第一章\n新正文",
                chapter_path=["新第一章"],
                page_range=(1, 1),
                token_count=50,
                chunk_type=ChunkType.COMPLETE_CHAPTER,
                needs_prior_summary=False,
                chunk_index=0,
                contained_chapters=[],
            ),
        ]
        chunk_list_v2 = ChunkList(source="v2.pdf", chunks=chunks_v2, total_tokens=50, chapter_count=1)

        await save_chunks(
            chunk_list_v2,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )

        # 加载应返回第二次保存的内容
        loaded = await load_chunks(
            "300274", "2024-annual",
        )
        assert loaded is not None
        assert loaded.chunks[0].text == "# 新第一章\n新正文"
        assert len(loaded.chunks) == 1

    @pytest.mark.asyncio
    async def test_contained_chapters_persistence(self, test_engine, chunk_with_contained_chapters, tmp_path):
        """contained_chapters 信息应能正确序列化/反序列化。"""
        storage_dir = tmp_path / "chunks"

        await save_chunks(
            chunk_with_contained_chapters,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )

        loaded = await load_chunks(
            "300274", "2024-annual",
        )

        assert loaded is not None
        assert len(loaded.chunks) == 1
        # 验证 contained_chapters 被正确恢复
        assert len(loaded.chunks[0].contained_chapters) == 2
        titles = {c.title for c in loaded.chunks[0].contained_chapters}
        assert titles == {"第一节", "第二节"}

    @pytest.mark.asyncio
    async def test_multiple_stocks(self, test_engine, sample_chunk_list, tmp_path):
        """多股票数据应相互隔离。"""
        storage_dir = tmp_path / "chunks"

        # 保存股票 A
        await save_chunks(
            sample_chunk_list,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )

        # 保存股票 B（不同内容）
        chunks_b = [
            Chunk(
                text="# 股票 B 章节\n内容",
                chapter_path=["股票B章节"],
                page_range=(1, 2),
                token_count=50,
                chunk_type=ChunkType.COMPLETE_CHAPTER,
                needs_prior_summary=False,
                chunk_index=0,
                contained_chapters=[],
            ),
        ]
        chunk_list_b = ChunkList(source="b.pdf", chunks=chunks_b, total_tokens=50, chapter_count=1)
        await save_chunks(
            chunk_list_b,
            stock_code="600000",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )

        # 加载股票 A
        loaded_a = await load_chunks("300274", "2024-annual")
        assert loaded_a is not None
        assert loaded_a.chunks[0].text == "# 第一章\n正文内容"

        # 加载股票 B
        loaded_b = await load_chunks("600000", "2024-annual")
        assert loaded_b is not None
        assert loaded_b.chunks[0].text == "# 股票 B 章节\n内容"

    @pytest.mark.asyncio
    async def test_empty_chunklist(self, test_engine, tmp_path):
        """空 ChunkList 应能正确处理。"""
        storage_dir = tmp_path / "chunks"
        empty_list = ChunkList(source="empty.pdf", chunks=[], total_tokens=0, chapter_count=0)

        await save_chunks(
            empty_list,
            stock_code="300274",
            report_date="2024-annual",
            storage_dir=storage_dir,
        )

        loaded = await load_chunks("300274", "2024-annual")
        assert loaded is not None
        assert len(loaded.chunks) == 0
        assert loaded.total_tokens == 0
