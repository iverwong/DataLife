"""章节合并器测试。

验证：
- 单 Chunk 章节直接包装
- 多 Chunk 章节 LLM 合并
- 合并失败降级为拼接
"""
from __future__ import annotations

import os

import pytest
from unittest.mock import patch

from pydantic_ai.models.test import TestModel

from core.data.summarizing.summary_models import ChapterSummary, ChunkSummaryOutput
from core.data.summarizing.chapter_merger import (
    build_single_chunk_chapter,
    merge_chapter_summaries,
)


# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def single_summary() -> ChunkSummaryOutput:
    """单 Chunk 章节的摘要输出。"""
    return ChunkSummaryOutput(
        chapter_title="第一节",
        chapter_path=["第一节"],
        key_points=["要点A"],
        detailed_summary="第一节的详细摘要内容",
        context_brief="第一节的上下文提示信息",
    )


@pytest.fixture
def multi_summaries() -> list[ChunkSummaryOutput]:
    """多 Chunk 章节的 3 个子块摘要（模拟财报附注超长章节被切为 3 块）。"""
    return [
        ChunkSummaryOutput(
            chapter_title="附注",
            chapter_path=["第十一节 财务报告", "附注"],
            key_points=[f"子块{i}要点"],
            detailed_summary=f"子块{i}的详细摘要内容，用于测试章节合并",
            context_brief=f"子块{i}的上下文信息，用于测试合并流程",
        )
        for i in range(3)
    ]


@pytest.fixture
def merged_output() -> ChunkSummaryOutput:
    """模拟 LLM 合并后的章节摘要。"""
    return ChunkSummaryOutput(
        chapter_title="附注",
        chapter_path=["第十一节 财务报告", "附注"],
        key_points=["合并后要点1", "合并后要点2"],
        detailed_summary="附注章节的统一摘要内容，涵盖所有子块的关键数据。",
        context_brief="附注章节概述了财务报告详细数据内容。",
    )


# ── build_single_chunk_chapter ─────────────────────────
class TestBuildSingleChunkChapter:
    def test_wraps_correctly(self, single_summary: ChunkSummaryOutput) -> None:
        """单 Chunk 直接包装为 ChapterSummary，chunk_count=1。"""
        ch = build_single_chunk_chapter(single_summary)
        assert isinstance(ch, ChapterSummary)
        assert ch.chunk_count == 1
        assert ch.chapter_title == "第一节"
        assert ch.summary is single_summary


# ── merge_chapter_summaries ────────────────────────────
class TestMergeChapterSummaries:
    @pytest.mark.asyncio
    async def test_single_item_no_llm_call(
        self, single_summary: ChunkSummaryOutput
    ) -> None:
        """仅 1 个子块时不调用 LLM，直接包装返回。"""
        result = await merge_chapter_summaries(
            [single_summary],
            chapter_title="第一节",
            chapter_path=["第一节"],
        )
        assert result.chunk_count == 1

    @pytest.mark.asyncio
    async def test_multi_chunk_merge(
        self,
        multi_summaries: list[ChunkSummaryOutput],
        merged_output: ChunkSummaryOutput,
    ) -> None:
        """多子块调用 LLM 合并，返回合并后的 ChapterSummary。"""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            from core.agents.chapter_merger_agent import chapter_merger_agent

            test_model = TestModel(
                custom_output_args=merged_output.model_dump()
            )
            with chapter_merger_agent.override(model=test_model):
                result = await merge_chapter_summaries(
                    multi_summaries,
                    chapter_title="附注",
                    chapter_path=["第十一节 财务报告", "附注"],
                )
        assert result.chunk_count == 3
        assert "合并后要点1" in result.summary.key_points

    @pytest.mark.asyncio
    async def test_merge_failure_degrades(
        self, multi_summaries: list[ChunkSummaryOutput]
    ) -> None:
        """合并 LLM 失败时降级为子块摘要拼接。"""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            from core.agents.chapter_merger_agent import chapter_merger_agent

            with patch.object(
                chapter_merger_agent,
                "run",
                side_effect=Exception("LLM merge failed"),
            ):
                result = await merge_chapter_summaries(
                    multi_summaries,
                    chapter_title="附注",
                    chapter_path=["第十一节 财务报告", "附注"],
                )
        # 降级结果仍然是 ChapterSummary
        assert isinstance(result, ChapterSummary)
        assert result.chunk_count == 3
        # 降级摘要应包含各子块内容
        for i in range(3):
            assert f"子块{i}的详细摘要内容" in result.summary.detailed_summary
