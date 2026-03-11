"""chunk_pipeline 直通路径测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.data.models import (
    ChunkList,
    ChunkType,
    ParsedDocument,
    ParsedPage,
)
from core.data.token_counter import count_tokens


def _make_parsed_doc(total_tokens_approx: int, source: str = "test.pdf") -> tuple[ParsedDocument, bytes]:
    """构造指定大致 token 量的 ParsedDocument 和空 PDF bytes。

    Args:
        total_tokens_approx: 目标 token 数（大致）。
        source: 来源标识。

    Returns:
        (ParsedDocument, pdf_bytes) 元组。
    """
    # 每个 "测试。" 约 2 tokens，按需重复
    repeat = max(total_tokens_approx // 2, 1)
    text = "测试。" * repeat
    page = ParsedPage(page_number=1, markdown_text=text)
    parsed = ParsedDocument(source=source, page_count=1, chunks=[page])
    # 空 PDF bytes（直通路径不需要真实 PDF 内容，但 pymupdf.open 需要）
    # 测试中 mock 掉 pymupdf.open
    return parsed, b"fake-pdf"


class TestChunkPipelineBypass:
    """chunk_pipeline 直通路径测试。"""

    @pytest.mark.asyncio
    async def test_bypass_triggered_under_3x(self):
        """文档 token 数 < 3 * max_tokens 时应走直通路径，跳过章节识别。

        fixture 设计：max_tokens=100, 文档约 200 tokens (< 300)
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(200)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf, \
             patch("core.data.chunk_pipeline.detect_chapters") as mock_detect:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=100, persist=False
            )
            # 直通路径不应调用 detect_chapters
            mock_detect.assert_not_called()
            assert isinstance(result, ChunkList)
            assert len(result.chunks) >= 1
            assert all(c.chunk_type == ChunkType.TOKEN_WINDOW for c in result.chunks)

    @pytest.mark.asyncio
    async def test_bypass_not_triggered_over_3x(self):
        """文档 token 数 >= 3 * max_tokens 时应走正常章节识别路径。

        fixture 设计：max_tokens=100, 文档约 400 tokens (>= 300)
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(400)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf, \
             patch("core.data.chunk_pipeline.detect_chapters", return_value=[]) as mock_detect, \
             patch("core.data.chunk_pipeline.build_chunks") as mock_build:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            mock_build.return_value = ChunkList(
                source=parsed.source, chunks=[], total_tokens=0, chapter_count=0
            )
            await chunk_document(
                content, parsed, max_tokens=100, persist=False
            )
            # 正常路径应调用 detect_chapters
            mock_detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_bypass_single_chunk_for_short_doc(self):
        """文档 token 数 <= max_tokens 时直通应产出单个 chunk。

        fixture 设计：max_tokens=8000, 文档约 100 tokens
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(100)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=8000, persist=False
            )
            assert len(result.chunks) == 1
            assert result.chunks[0].text == parsed.full_text

    @pytest.mark.asyncio
    async def test_bypass_chunks_cover_full_text(self):
        """直通路径产出的 chunks 应覆盖全文（无内容丢失）。

        fixture 设计：max_tokens=100, 文档约 250 tokens, overlap=20
        验证：所有 chunk 文本去除 overlap 后拼接 = 原始 full_text
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(250)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=100, persist=False
            )
            # 所有 chunk 的 token 数之和（含 overlap）应 >= 原始 token 数
            total_original = count_tokens(parsed.full_text)
            assert result.total_tokens >= total_original
            # 每个 chunk 不超过 max_tokens
            for c in result.chunks:
                assert c.token_count <= 100
