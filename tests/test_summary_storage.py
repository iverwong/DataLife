"""摘要存储测试。

使用临时 SQLite 数据库，验证表创建和读写。
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from core.data.models import Chunk, ChunkList, ChunkType
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
from core.data.summarizing.summary_pipeline import summarize_document


def _make_mock_summary(title: str, path: list[str], idx: int) -> ChunkSummaryOutput:
    """生成模拟摘要输出的辅助函数。"""
    return ChunkSummaryOutput(
        chapter_title=title,
        chapter_path=path,
        key_points=[f"{title}要点{idx}"],
        detailed_summary=f"{title}的详细摘要内容，编号{idx}，用于测试摘要存储功能",
        context_brief=f"{title}的上下文提示信息，编号{idx}",
    )


def _make_chapter_summary(title: str) -> ChapterSummary:
    """生成模拟章节摘要的辅助函数。"""
    return ChapterSummary(
        chapter_title=title,
        chapter_path=[title],
        summary=ChunkSummaryOutput(
            chapter_title=title,
            chapter_path=[title],
            key_points=[f"{title}要点"],
            detailed_summary=f"{title}的详细摘要内容，用于测试章节摘要功能",
            context_brief=f"{title}的上下文提示信息",
        ),
        chunk_count=1,
    )


@pytest.fixture
def two_chapter_chunk_list() -> ChunkList:
    """包含 2 个章节（共 3 个 Chunk）的 ChunkList。

    章节 A（单 Chunk）：路径 1 直出
    章节 B（2 个 Chunk）：路径 2 合并
    """
    return ChunkList(
        source="600000_2024-12-31",
        chunks=[
            # 章节 A：单 Chunk
            Chunk(
                text="章节A完整内容..." * 30,
                chapter_path=["第一节"],
                page_range=(1, 5),
                token_count=300,
                chunk_type=ChunkType.COMPLETE_CHAPTER,
                needs_prior_summary=False,
                chunk_index=0,
                contained_chapters=None,
            ),
            # 章节 B：子块 0
            Chunk(
                text="章节B第一部分..." * 30,
                chapter_path=["第二节"],
                page_range=(6, 10),
                token_count=400,
                chunk_type=ChunkType.TOKEN_WINDOW,
                needs_prior_summary=False,
                chunk_index=0,
                contained_chapters=None,
            ),
            # 章节 B：子块 1
            Chunk(
                text="章节B第二部分..." * 30,
                chapter_path=["第二节"],
                page_range=(10, 15),
                token_count=400,
                chunk_type=ChunkType.TOKEN_WINDOW,
                needs_prior_summary=True,
                chunk_index=1,
                contained_chapters=None,
            ),
        ],
        total_tokens=1100,
        chapter_count=2,
    )


@pytest.fixture
def sample_chunk_summary() -> ChunkSummaryOutput:
    return ChunkSummaryOutput(
        chapter_title="第一节",
        chapter_path=["第一节"],
        key_points=["要点1"],
        detailed_summary="这是第一节的详细摘要内容，用于测试",
        key_data=[KeyDataItem(label="营收", value=1e9, unit="元")],
        context_brief="这是第一节的上下文提示信息",
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
                detailed_summary="这是第一节的详细摘要内容，用于测试章节摘要功能",
                key_data=[KeyDataItem(label="营收", value=1e9, unit="元")],
                context_brief="这是第一节的上下文提示信息",
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


class TestChapterSummaryUpsert:
    """save_chapter_summary 幂等性修复测试。

    覆盖范围：首次插入、重复插入 upsert、不同章节独立存储。
    外部依赖：test_engine fixture（in-memory SQLite）。
    """

    @pytest.mark.asyncio
    async def test_duplicate_save_does_not_create_duplicate(
        self, test_engine
    ) -> None:
        """Given: 对同一份报告的同一章节调用两次 save_chapter_summary
        When: 第二次调用时记录已存在
        Then: 数据库中只有 1 条记录（upsert），而非 2 条
        验证要点：幂等性"""
        chapter = ChapterSummary(
            chapter_title="第一节",
            chapter_path=["第一节"],
            summary=ChunkSummaryOutput(
                chapter_title="第一节", chapter_path=["第一节"],
                key_points=["v1"], detailed_summary="第一节版本1的详细摘要内容",
                context_brief="第一节版本1的上下文提示",
            ),
            chunk_count=1,
        )
        await save_chapter_summary(chapter, stock_code="600000", report_date="2024-12-31")
        # 第二次保存（更新内容）
        chapter_v2 = ChapterSummary(
            chapter_title="第一节",
            chapter_path=["第一节"],
            summary=ChunkSummaryOutput(
                chapter_title="第一节", chapter_path=["第一节"],
                key_points=["v2"], detailed_summary="第一节版本2的详细摘要内容",
                context_brief="第一节版本2的上下文提示",
            ),
            chunk_count=1,
        )
        await save_chapter_summary(chapter_v2, stock_code="600000", report_date="2024-12-31")

        # 验证只有 1 条记录
        from core.db import get_session
        from core.db.models import ChapterSummaryRecord
        from sqlalchemy import select, func

        async with get_session() as session:
            count = await session.scalar(
                select(func.count()).select_from(ChapterSummaryRecord)
                .where(ChapterSummaryRecord.stock_code == "600000")
                .where(ChapterSummaryRecord.report_date == "2024-12-31")
                .where(ChapterSummaryRecord.chapter_title == "第一节")
            )
        assert count == 1


class TestExceptionHierarchy:
    """异常类继承链验证测试。

    覆盖范围：SummaryStorageError 是否为 SummarizationError 子类。
    """

    def test_summary_storage_error_is_summarization_error(self) -> None:
        """Given: summary_storage 模块抛出 SummaryStorageError
        When: 上层 except SummarizationError 捕获
        Then: 能够被捕获（继承链正确）
        验证要点：统一异常层级"""
        from core.data.summarizing.summary_storage import SummaryStorageError
        from core.data.exceptions import SummarizationError
        assert issubclass(SummaryStorageError, SummarizationError)


class TestTimezoneAwareness:
    """datetime 时区感知修复测试。

    覆盖范围：save_chapter_summary 和 save_document_summary 的 created_at 字段。
    """

    @pytest.mark.asyncio
    async def test_chapter_summary_created_at_has_timezone(
        self, test_engine
    ) -> None:
        """Given: 保存一条章节摘要
        When: 读取 created_at 字段
        Then: ISO 字符串包含时区信息（+ 或 Z 后缀）
        验证要点：非 naive datetime"""
        chapter = ChapterSummary(
            chapter_title="第一节",
            chapter_path=["第一节"],
            summary=ChunkSummaryOutput(
                chapter_title="第一节", chapter_path=["第一节"],
                key_points=["p"], detailed_summary="第一节的详细摘要内容用于测试",
                context_brief="第一节的上下文提示信息",
            ),
            chunk_count=1,
        )
        await save_chapter_summary(chapter, stock_code="600000", report_date="2024-12-31")

        from core.db import get_session
        from core.db.models import ChapterSummaryRecord
        from sqlalchemy import select

        async with get_session() as session:
            record = (await session.execute(
                select(ChapterSummaryRecord)
            )).scalar_one()
        # created_at 应包含时区标识
        assert "+" in record.created_at or "Z" in record.created_at


class TestChunkSummaryPersistence:
    """save_chunk_summary 管道集成与重构测试。

    覆盖范围：管道调用集成、persist 开关、upsert 幂等性。
    外部依赖：test_engine fixture + mock summarize_chunk。
    """

    @pytest.mark.asyncio
    async def test_pipeline_calls_save_chunk_summary_on_persist(
        self, two_chapter_chunk_list: ChunkList, test_engine
    ) -> None:
        """Given: summarize_document(persist=True, chunk_meta_ids=[101,102,103])，3 个 Chunk 全部成功
        When: 管道执行完毕
        Then: save_chunk_summary 被调用 3 次，每次传入正确的 chunk_meta_id
        验证要点：管道集成 — persist=True + chunk_meta_ids 时逐 Chunk 持久化"""
        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock,
            side_effect=lambda chunk, ctx, **kw: _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, 0
            ),
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=_make_chapter_summary("第二节"),
        ), patch(
            "core.data.summarizing.summary_pipeline.save_chunk_summary",
            new_callable=AsyncMock,
        ) as mock_save:
            await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000", report_date="2024-12-31",
                chunk_meta_ids=[101, 102, 103],
                persist=True,
            )
        assert mock_save.call_count == 3
        # 验证每次调用传入的 chunk_meta_id 正确
        for idx, call in enumerate(mock_save.call_args_list):
            assert call.args[0] == [101, 102, 103][idx]

    @pytest.mark.asyncio
    async def test_persist_false_skips_chunk_save(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """Given: summarize_document(persist=False)
        When: 管道执行完毕
        Then: save_chunk_summary 未被调用
        验证要点：persist=False 不触发持久化"""
        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock,
            side_effect=lambda chunk, ctx, **kw: _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, 0
            ),
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=_make_chapter_summary("第二节"),
        ), patch(
            "core.data.summarizing.summary_pipeline.save_chunk_summary",
            new_callable=AsyncMock,
        ) as mock_save:
            await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000", report_date="2024-12-31", persist=False,
            )
        assert mock_save.call_count == 0

    @pytest.mark.asyncio
    async def test_chunk_summary_upsert_no_duplicate(
        self, test_engine
    ) -> None:
        """Given: 同一 chunk_meta_id 保存两次
        When: 第二次调用
        Then: 数据库中只有 1 条记录
        验证要点：upsert 幂等性"""
        # 先创建关联的 ChunkMetaRecord
        from core.db import get_session
        from core.db.models import ChunkMetaRecord, ChunkSummaryRecord
        from sqlalchemy import select, func

        async with get_session() as session:
            meta = ChunkMetaRecord(
                stock_code="600000", report_date="2024-12-31",
                chunk_index=0, chapter_title="第一节",
                chapter_path='["第一节"]',
                page_start=1, page_end=5,
                token_count=100, chunk_type="complete_chapter",
                needs_prior_summary=0, md_file_path="/tmp/test.md",
            )
            session.add(meta)
            await session.flush()
            meta_id = meta.id

        summary = ChunkSummaryOutput(
            chapter_title="第一节", chapter_path=["第一节"],
            key_points=["v1"], detailed_summary="第一节版本1的详细摘要内容",
            context_brief="第一节版本1的上下文",
        )
        await save_chunk_summary(meta_id, summary)
        summary_v2 = ChunkSummaryOutput(
            chapter_title="第一节", chapter_path=["第一节"],
            key_points=["v2"], detailed_summary="第一节版本2的详细摘要内容",
            context_brief="第一节版本2的上下文",
        )
        await save_chunk_summary(meta_id, summary_v2)

        async with get_session() as session:
            count = await session.scalar(
                select(func.count()).select_from(ChunkSummaryRecord)
                .where(ChunkSummaryRecord.chunk_meta_id == meta_id)
            )
        assert count == 1
