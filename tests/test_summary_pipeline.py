"""摘要编排管道集成测试。

mock LLM 调用，验证端到端流程：
ChunkList → 逐 Chunk 摘要 → 章节合并 → 文档拼接 → 持久化
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from core.data.models import Chunk, ChunkList, ChunkType
from core.data.exceptions import LLMResponseError
from core.data.summarizing.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
)
from core.data.summarizing.summary_pipeline import summarize_document


# ── Fixtures ────────────────────────────────────────────
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


def _make_mock_summary(title: str, path: list[str], idx: int) -> ChunkSummaryOutput:
    """生成模拟摘要输出的辅助函数。"""
    return ChunkSummaryOutput(
        chapter_title=title,
        chapter_path=path,
        key_points=[f"{title}要点{idx}"],
        detailed_summary=f"{title}摘要{idx}",
        context_brief=f"{title}上下文{idx}",
    )


# ── summarize_document ─────────────────────────────────
class TestSummarizeDocument:
    @pytest.mark.asyncio
    async def test_end_to_end_no_persist(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """端到端流程（不持久化），验证 DocumentSummary 结构。"""
        call_count = 0

        async def mock_summarize(chunk, ctx, **kwargs):
            nonlocal call_count
            result = _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, call_count
            )
            call_count += 1
            return result

        merged_output = ChunkSummaryOutput(
            chapter_title="第二节",
            chapter_path=["第二节"],
            key_points=["合并要点"],
            detailed_summary="第二节合并摘要",
            context_brief="第二节合并上下文",
        )

        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock,
            side_effect=mock_summarize,
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=pytest.importorskip(
                "core.data.summarizing.summary_models"
            ).ChapterSummary(
                chapter_title="第二节",
                chapter_path=["第二节"],
                summary=merged_output,
                chunk_count=2,
            ),
        ):
            result = await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000",
                report_date="2024-12-31",
                persist=False,
            )

        assert isinstance(result, DocumentSummary)
        assert result.total_chapters == 2
        assert result.total_chunks_processed == 3
        assert len(result.chapter_summaries) == 2
        # 章节 A：单 Chunk 直出，chunk_count=1
        assert result.chapter_summaries[0].chunk_count == 1
        # 章节 B：多 Chunk 合并，chunk_count=2
        assert result.chapter_summaries[1].chunk_count == 2

    @pytest.mark.asyncio
    async def test_context_brief_chaining(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """验证 context_brief 在 Chunk 间正确传递。

        - 章节 A 的 Chunk[0]：无 context_brief（首块）
        - 章节 B 的 Chunk[0]：注入章节 A 最后一块的 context_brief
        - 章节 B 的 Chunk[1]：注入章节 B Chunk[0] 的 context_brief
        """
        captured_contexts: list[str | None] = []

        async def mock_summarize(chunk, ctx, **kwargs):
            captured_contexts.append(ctx.context_brief)
            return _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, len(captured_contexts)
            )

        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock,
            side_effect=mock_summarize,
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=pytest.importorskip(
                "core.data.summarizing.summary_models"
            ).ChapterSummary(
                chapter_title="第二节",
                chapter_path=["第二节"],
                summary=_make_mock_summary("第二节", ["第二节"], 99),
                chunk_count=2,
            ),
        ):
            await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000",
                report_date="2024-12-31",
                persist=False,
            )

        assert len(captured_contexts) == 3
        # Chunk 0（章节 A 首块）：无 context_brief
        assert captured_contexts[0] is None
        # Chunk 1（章节 B 首块）：注入章节 A 的 context_brief
        assert captured_contexts[1] is not None
        # Chunk 2（章节 B 子块 1）：注入章节 B Chunk 0 的 context_brief
        assert captured_contexts[2] is not None
        assert captured_contexts[2] != captured_contexts[1]  # 不同来源


# ── TestChapterKeyConsistency ────────────────────────────────────────────────
class TestChapterKeyConsistency:
    """chapter_key 类型一致性修复测试。

    覆盖范围：同章节 context_brief 传递、跨章节切换、章节回跳（A→B→A）。
    外部依赖全部 mock：summarize_chunk。
    """

    @pytest.mark.asyncio
    async def test_same_chapter_uses_chapter_specific_brief(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """Given: 章节 B 有 2 个连续子块（chunk_index 0 和 1）
        When: 逐 Chunk 摘要时，第二个子块获取 context_brief
        Then: 使用的是同章节上一子块的 context_brief（通过 last_context_brief_by_chapter），
              而非简单的 last_chapter_brief
        验证要点：同章节分支被正确命中"""
        captured_contexts: list[str | None] = []

        async def mock_summarize(chunk, ctx, **kwargs):
            captured_contexts.append(ctx.context_brief)
            title = chunk.chapter_path[-1]
            # 为不同章节返回不同的 context_brief
            if title == "第一节":
                brief = "章节A专属brief"
            elif len(captured_contexts) == 2:  # 章节B第一个子块
                brief = "章节B子块0的brief"
            else:
                brief = "章节B子块1的brief"
            return ChunkSummaryOutput(
                chapter_title=title,
                chapter_path=chunk.chapter_path,
                key_points=[f"{title}要点"],
                detailed_summary=f"{title}摘要",
                context_brief=brief,
            )

        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock, side_effect=mock_summarize,
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=ChapterSummary(
                chapter_title="第二节", chapter_path=["第二节"],
                summary=ChunkSummaryOutput(
                    chapter_title="第二节", chapter_path=["第二节"],
                    key_points=["x"], detailed_summary="x", context_brief="x",
                ),
                chunk_count=2,
            ),
        ):
            await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000", report_date="2024-12-31", persist=False,
            )

        # 章节B的第二个子块（index 2）应该收到章节B子块0的brief
        # 而非章节A的brief
        assert captured_contexts[2] == "章节B子块0的brief"

    @pytest.mark.asyncio
    async def test_chapter_jump_back_uses_correct_brief(self) -> None:
        """Given: Chunk 序列为 A→B→A（章节回跳）
        When: 第三个 Chunk（回到章节 A）获取 context_brief
        Then: 使用 last_context_brief_by_chapter 中章节 A 的记录，
              而非章节 B 的 last_chapter_brief
        验证要点：章节回跳场景下 dict 查找正确"""
        chunks = ChunkList(
            source="test",
            chunks=[
                Chunk(text="A内容", chapter_path=["章节A"], page_range=(1, 5),
                      token_count=100, chunk_type=ChunkType.COMPLETE_CHAPTER,
                      needs_prior_summary=False, chunk_index=0, contained_chapters=None),
                Chunk(text="B内容", chapter_path=["章节B"], page_range=(6, 10),
                      token_count=100, chunk_type=ChunkType.COMPLETE_CHAPTER,
                      needs_prior_summary=False, chunk_index=0, contained_chapters=None),
                Chunk(text="A后续", chapter_path=["章节A"], page_range=(11, 15),
                      token_count=100, chunk_type=ChunkType.TOKEN_WINDOW,
                      needs_prior_summary=True, chunk_index=1, contained_chapters=None),
            ],
            total_tokens=300, chapter_count=2,
        )
        captured_contexts: list[str | None] = []

        async def mock_summarize(chunk, ctx, **kwargs):
            captured_contexts.append(ctx.context_brief)
            title = chunk.chapter_path[-1]
            return ChunkSummaryOutput(
                chapter_title=title, chapter_path=chunk.chapter_path,
                key_points=["p"], detailed_summary="s",
                context_brief=f"{title}_brief",
            )

        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock, side_effect=mock_summarize,
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=ChapterSummary(
                chapter_title="章节A", chapter_path=["章节A"],
                summary=ChunkSummaryOutput(
                    chapter_title="章节A", chapter_path=["章节A"],
                    key_points=["x"], detailed_summary="x", context_brief="x",
                ),
                chunk_count=2,
            ),
        ):
            await summarize_document(
                chunks, stock_code="T", report_date="2025-01-01", persist=False,
            )

        # 第三个 Chunk（回到章节A）应该收到章节A第一个子块的brief
        assert captured_contexts[2] == "章节A_brief"


# ── TestChunkFailureHandling ─────────────────────────────────────────────────
class TestChunkFailureHandling:
    """单个 Chunk 摘要失败容错测试。

    覆盖范围：中间 Chunk 失败继续、全部失败、失败后 context_brief 链处理。
    外部依赖全部 mock：summarize_chunk。
    """

    @pytest.mark.asyncio
    async def test_single_chunk_failure_does_not_abort(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """Given: 3 个 Chunk 中第 2 个抛出 LLMResponseError
        When: summarize_document 执行
        Then: 函数不抛异常，返回 DocumentSummary，成功的 Chunk 被保留
        验证要点：管道不因单个 Chunk 失败而中断"""
        call_count = 0

        async def mock_summarize(chunk, ctx, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise LLMResponseError("API timeout")
            return _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, call_count
            )

        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock, side_effect=mock_summarize,
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=ChapterSummary(
                chapter_title="第二节", chapter_path=["第二节"],
                summary=_make_mock_summary("第二节", ["第二节"], 99),
                chunk_count=1,  # 只有 1 个成功的子块
            ),
        ):
            result = await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000", report_date="2024-12-31", persist=False,
            )

        assert isinstance(result, DocumentSummary)
        # 所有 3 个 Chunk 都被尝试
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_failed_chunk_context_brief_falls_back(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """Given: 第 2 个 Chunk（章节B子块0）失败
        When: 第 3 个 Chunk（章节B子块1）获取 context_brief
        Then: 使用上一个成功的 context_brief（降级策略），而非 None
        验证要点：失败 Chunk 不破坏 context_brief 链"""
        captured_contexts: list[str | None] = []
        call_count = 0

        async def mock_summarize(chunk, ctx, **kwargs):
            nonlocal call_count
            call_count += 1
            captured_contexts.append(ctx.context_brief)
            if call_count == 2:
                raise LLMResponseError("API timeout")
            return _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, call_count
            )

        with patch(
            "core.data.summarizing.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock, side_effect=mock_summarize,
        ), patch(
            "core.data.summarizing.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=ChapterSummary(
                chapter_title="第二节", chapter_path=["第二节"],
                summary=_make_mock_summary("第二节", ["第二节"], 99),
                chunk_count=1,
            ),
        ):
            await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000", report_date="2024-12-31", persist=False,
            )

        # 第 3 个 Chunk 的 context_brief 应该不为 None（降级到可用值）
        assert captured_contexts[2] is not None
