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
    """chunk_pipeline 直通路径测试。

    业务逻辑：只有整篇文档能塞进一个 chunk（total_tokens <= max_tokens）时才直通，
    否则走章节识别路径。
    """

    @pytest.mark.asyncio
    async def test_bypass_triggered_when_doc_fits_in_single_chunk(self):
        """文档 token 数 <= max_tokens 时应走直通路径，跳过章节识别。

        fixture 设计：max_tokens=100, overlap_tokens=20, 文档约 50 tokens (<= 100)
        """
        from core.data.chunking.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(50)
        with patch("core.data.chunking.chunk_pipeline.pymupdf") as mock_pymupdf, \
             patch("core.data.chunking.chunk_pipeline.detect_chapters") as mock_detect:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=100, overlap_tokens=20, persist=False
            )
            # 直通路径不应调用 detect_chapters
            mock_detect.assert_not_called()
            assert isinstance(result, ChunkList)
            assert len(result.chunks) == 1
            assert all(c.chunk_type == ChunkType.TOKEN_WINDOW for c in result.chunks)

    @pytest.mark.asyncio
    async def test_bypass_not_triggered_when_doc_exceeds_chunk(self):
        """文档 token 数 > max_tokens 时应走正常章节识别路径。

        fixture 设计：max_tokens=100, overlap_tokens=20, 文档约 200 tokens (> 100)
        """
        from core.data.chunking.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(200)
        with patch("core.data.chunking.chunk_pipeline.pymupdf") as mock_pymupdf, \
             patch("core.data.chunking.chunk_pipeline.detect_chapters", return_value=[]) as mock_detect, \
             patch("core.data.chunking.chunk_pipeline.build_chunks") as mock_build:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            mock_build.return_value = ChunkList(
                source=parsed.source, chunks=[], total_tokens=0, chapter_count=0
            )
            await chunk_document(
                content, parsed, max_tokens=100, overlap_tokens=20, persist=False
            )
            # 正常路径应调用 detect_chapters
            mock_detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_bypass_single_chunk_for_short_doc(self):
        """文档 token 数 <= max_tokens 时直通应产出单个 chunk。

        fixture 设计：max_tokens=8000, 文档约 100 tokens
        """
        from core.data.chunking.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(100)
        with patch("core.data.chunking.chunk_pipeline.pymupdf") as mock_pymupdf:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=8000, persist=False
            )
            assert len(result.chunks) == 1
            assert result.chunks[0].text == parsed.full_text


def test_default_max_tokens_is_120k():
    """Given: chunk_pipeline 模块默认常量
    When: 导入 DEFAULT_MAX_TOKENS
    Then: 值为 120000
    验证要点：常量已更新"""
    from core.data.chunking.chunk_pipeline import DEFAULT_MAX_TOKENS
    assert DEFAULT_MAX_TOKENS == 120_000
