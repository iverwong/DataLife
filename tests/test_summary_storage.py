"""摘要存储测试。

使用临时 SQLite 数据库，验证表创建和读写。
"""
from __future__ import annotations

import pytest

from core.data.summarizing.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
)
from core.data.summarizing.summary_storage import (
    load_document_summary,
    save_chapter_summary,
    save_chunk_summary,
    save_document_summary,
)


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


class TestSaveAndLoad:
    """保存/加载测试。"""

    @pytest.mark.asyncio
    async def test_save_and_load_document_summary(self, test_engine):
        """保存并加载完整文档摘要，验证往返一致性。"""
        # 需要先准备 chunk_meta 记录（提供外键）
        from core.db import get_session
        from core.db.models import ChunkMetaRecord

        async with get_session() as session:
            meta = ChunkMetaRecord(
                stock_code="600000",
                report_date="2024-12-31",
                chunk_index=0,
                chapter_title="第一节",
                chapter_path='["第一节"]',
                contained_chapters=None,
                page_start=1,
                page_end=5,
                token_count=100,
                chunk_type="complete_chapter",
                needs_prior_summary=0,
                md_file_path="/tmp/test.md",
            )
            session.add(meta)
            # 不需要 commit，get_session 会自动 commit

        doc = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[],
            all_key_points=["全文要点"],
            all_key_data=[KeyDataItem(label="总资产", value=1e10, unit="元")],
            total_chunks_processed=8,
            total_chapters=4,
        )
        await save_document_summary(doc)
        loaded = await load_document_summary("600000", "2024-12-31")
        assert loaded is not None
        assert loaded.source == "600000_2024-12-31"
        assert loaded.total_chunks_processed == 8
        assert len(loaded.all_key_data) == 1

    @pytest.mark.asyncio
    async def test_save_chunk_summary(self, test_engine, sample_chunk_summary):
        """保存 Chunk 摘要并验证返回 ID。"""
        # 需要先准备 chunk_meta 记录
        from core.db import get_session
        from core.db.models import ChunkMetaRecord

        async with get_session() as session:
            meta = ChunkMetaRecord(
                stock_code="600000",
                report_date="2024-12-31",
                chunk_index=0,
                chapter_title="第一节",
                chapter_path='["第一节"]',
                contained_chapters=None,
                page_start=1,
                page_end=5,
                token_count=100,
                chunk_type="complete_chapter",
                needs_prior_summary=0,
                md_file_path="/tmp/test.md",
            )
            session.add(meta)

        record_id = await save_chunk_summary(
            chunk_meta_id=1,
            summary=sample_chunk_summary,
        )
        assert isinstance(record_id, int)
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_save_chapter_summary(self, test_engine):
        """保存章节摘要并验证返回 ID。"""
        chapter = ChapterSummary(
            chapter_title="第一节",
            chapter_path=["第一节", "子节"],
            summary=ChunkSummaryOutput(
                chapter_title="第一节",
                chapter_path=["第一节", "子节"],
                key_points=["要点1"],
                detailed_summary="详细摘要",
                key_data=[KeyDataItem(label="营收", value=1e9, unit="元")],
                context_brief="上下文",
            ),
            chunk_count=2,
        )
        record_id = await save_chapter_summary(
            chapter=chapter,
            stock_code="600000",
            report_date="2024-12-31",
        )
        assert isinstance(record_id, int)
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_document_summary_upsert(self, test_engine):
        """验证先查后更新 upsert 语义。"""
        # 第一次保存
        doc1 = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[],
            all_key_points=["第一版要点"],
            all_key_data=[],
            total_chunks_processed=1,
            total_chapters=1,
        )
        await save_document_summary(doc1)

        # 加载验证
        loaded1 = await load_document_summary("600000", "2024-12-31")
        assert loaded1 is not None
        assert loaded1.all_key_points == ["第一版要点"]

        # 第二次保存（更新）
        doc2 = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[],
            all_key_points=["更新后的要点"],
            all_key_data=[],
            total_chunks_processed=2,
            total_chapters=1,
        )
        await save_document_summary(doc2)

        # 验证更新成功
        loaded2 = await load_document_summary("600000", "2024-12-31")
        assert loaded2 is not None
        assert loaded2.all_key_points == ["更新后的要点"]
        assert loaded2.total_chunks_processed == 2
