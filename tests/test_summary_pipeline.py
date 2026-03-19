"""摘要编排管道集成测试。

mock LLM 调用，验证端到端流程：
ChunkList → 逐 Chunk 摘要 → 章节合并 → 文档拼接 → 持久化
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.data.models import Chunk, ChunkList, ChunkType
from core.data.summarizing.summary_models import (
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
