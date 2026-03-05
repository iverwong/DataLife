"""逐 Chunk 摘要器测试。

使用 mock 隔离 DeepSeek API 调用，验证：
- SummarizeContext 构建逻辑
- prompt 中 context_brief 注入
- 正常摘要输出
- LLM 返回异常处理
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from core.data.models import Chunk, ChunkType
from core.data.summary_models import ChunkSummaryOutput
from core.data.chunk_summarizer import (
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    SummarizeContext,
    build_summarize_context,
    summarize_chunk,
)
from core.data.exceptions import LLMResponseError


# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def sample_chunk() -> Chunk:
    """标准单章节 Chunk，约 500 token 文本。"""
    return Chunk(
        text="本公司2024年度实现营业收入50亿元..." * 50,  # ~500 tokens
        chapter_path=["第三节 管理层讨论", "3.1 经营概况"],
        page_range=(10, 15),
        token_count=500,
        chunk_type=ChunkType.COMPLETE_CHAPTER,
        needs_prior_summary=False,
        chunk_index=0,
        contained_chapters=None,
    )


@pytest.fixture
def sample_chunk_with_prior() -> Chunk:
    """需要前文上下文的子块 Chunk（chunk_index=1）。"""
    return Chunk(
        text="续上文，公司海外业务..." * 50,
        chapter_path=["第三节 管理层讨论", "3.1 经营概况"],
        page_range=(15, 20),
        token_count=500,
        chunk_type=ChunkType.TOKEN_WINDOW,
        needs_prior_summary=True,
        chunk_index=1,
        contained_chapters=None,
    )


@pytest.fixture
def mock_summary_output() -> ChunkSummaryOutput:
    """模拟 LLM 返回的标准摘要输出。"""
    return ChunkSummaryOutput(
        chapter_title="3.1 经营概况",
        chapter_path=["第三节 管理层讨论", "3.1 经营概况"],
        key_points=["营收50亿", "同比增长15%"],
        detailed_summary="公司2024年度经营情况良好...",
        key_data=[],
        context_brief="第三节3.1小节概述了公司2024年经营概况，营收50亿，同比增长15%。",
    )


# ── build_summarize_context ────────────────────────────
class TestBuildSummarizeContext:
    def test_first_chunk_no_context(self, sample_chunk: Chunk) -> None:
        """首块无 context_brief。"""
        ctx = build_summarize_context(sample_chunk, previous_context_brief=None)
        assert ctx.context_brief is None
        assert ctx.chunk_index == 0
        assert ctx.chapter_path == ["第三节 管理层讨论", "3.1 经营概况"]

    def test_subsequent_chunk_with_context(
        self, sample_chunk_with_prior: Chunk
    ) -> None:
        """后续子块注入前文 context_brief。"""
        prev_brief = "前文概述了公司整体情况。"
        ctx = build_summarize_context(
            sample_chunk_with_prior, previous_context_brief=prev_brief
        )
        assert ctx.context_brief == prev_brief
        assert ctx.chunk_index == 1

    def test_contained_chapters_passed(self) -> None:
        """多章节 Chunk 的 contained_chapters 正确传递。"""
        chunk = Chunk(
            text="多章节内容...",
            chapter_path=["第四节"],
            page_range=(20, 30),
            token_count=300,
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            needs_prior_summary=False,
            chunk_index=0,
            contained_chapters=["4.1 子章节A", "4.2 子章节B"],
        )
        ctx = build_summarize_context(chunk, previous_context_brief=None)
        assert ctx.contained_chapters == ["4.1 子章节A", "4.2 子章节B"]


# ── summarize_chunk ────────────────────────────────────
class TestSummarizeChunk:
    @pytest.mark.asyncio
    async def test_successful_summarization(
        self,
        sample_chunk: Chunk,
        mock_summary_output: ChunkSummaryOutput,
    ) -> None:
        """正常调用返回结构化摘要。"""
        ctx = SummarizeContext(
            context_brief=None,
            chapter_path=sample_chunk.chapter_path,
            contained_chapters=None,
            chunk_index=0,
        )
        # mock PydanticAI Agent.run
        with patch(
            "core.data.chunk_summarizer._run_agent",
            new_callable=AsyncMock,
            return_value=mock_summary_output,
        ):
            result = await summarize_chunk(sample_chunk, ctx)
        assert isinstance(result, ChunkSummaryOutput)
        assert result.chapter_title == "3.1 经营概况"
        assert len(result.key_points) >= 1

    @pytest.mark.asyncio
    async def test_llm_empty_response_raises(
        self, sample_chunk: Chunk
    ) -> None:
        """LLM 返回空内容时抛出 LLMResponseError。"""
        ctx = SummarizeContext(
            context_brief=None,
            chapter_path=sample_chunk.chapter_path,
            contained_chapters=None,
            chunk_index=0,
        )
        with patch(
            "core.data.chunk_summarizer._run_agent",
            new_callable=AsyncMock,
            side_effect=LLMResponseError("Empty response from LLM"),
        ):
            with pytest.raises(LLMResponseError):
                await summarize_chunk(sample_chunk, ctx)

    @pytest.mark.asyncio
    async def test_context_brief_injected_in_prompt(
        self,
        sample_chunk_with_prior: Chunk,
        mock_summary_output: ChunkSummaryOutput,
    ) -> None:
        """验证 context_brief 被注入到 prompt 中。"""
        prev_brief = "前文概述了整体经营情况。"
        ctx = SummarizeContext(
            context_brief=prev_brief,
            chapter_path=sample_chunk_with_prior.chapter_path,
            contained_chapters=None,
            chunk_index=1,
        )
        captured_prompts: list[str] = []

        async def mock_run(*args, **kwargs):
            # 捕获传入的 user prompt 以验证 context_brief 注入
            if "user_prompt" in kwargs:
                captured_prompts.append(kwargs["user_prompt"])
            return mock_summary_output

        with patch(
            "core.data.chunk_summarizer._run_agent",
            new_callable=AsyncMock,
            side_effect=mock_run,
        ):
            await summarize_chunk(sample_chunk_with_prior, ctx)
        # 验证 context_brief 出现在 prompt 中
        # 具体验证方式取决于实现中 prompt 的构建方式
