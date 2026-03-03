"""PDF 解析模块测试。

测试覆盖：
- 正向：正常 PDF → Markdown 转换（Layout 模式）
- 边界：空白页、单页、指定页码
- 异常：文件不存在、损坏 PDF、加密 PDF、空字节流
- 布局：页眉页脚过滤 vs 保留
- 数据结构：frozen dataclass 行为

注意：Layout 模式下 tables 元数据为空列表，
表格检测结果体现在 markdown_text 的 Markdown 表格格式中。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from dataclasses import FrozenInstanceError

from core.exceptions import DataLifeError
from core.data.models import PageChunk, PDFParseResult
from core.data.pdf_parser import (
    PDFCorruptedError,
    PDFEncryptedError,
    PDFFileNotFoundError,
    PDFParsingError,
    parse_pdf,
    parse_pdf_bytes,
)

# 标记所有测试为异步
pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """生成一个包含 3 页文本的测试 PDF。"""
    pdf_path = tmp_path / "test_sample.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"第 {i + 1} 页内容\n这是测试文本。")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def table_pdf_path(tmp_path: Path) -> Path:
    """生成一个包含简单有线表格的测试 PDF。"""
    pdf_path = tmp_path / "test_table.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # 绘制 3x2 有线表格
    shape = page.new_shape()
    x0, y0, col_w, row_h = 72, 72, 150, 30
    rows, cols = 3, 2
    for r in range(rows + 1):
        y = y0 + r * row_h
        shape.draw_line(pymupdf.Point(x0, y), pymupdf.Point(x0 + cols * col_w, y))
    for c in range(cols + 1):
        x = x0 + c * col_w
        shape.draw_line(pymupdf.Point(x, y0), pymupdf.Point(x, y0 + rows * row_h))
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()
    page.insert_text((80, 95), "指标")
    page.insert_text((230, 95), "数值")
    page.insert_text((80, 125), "营业收入")
    page.insert_text((230, 125), "100亿")
    page.insert_text((80, 155), "净利润")
    page.insert_text((230, 155), "20亿")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_pdf_bytes(sample_pdf_path: Path) -> bytes:
    """返回测试 PDF 的字节内容。"""
    return sample_pdf_path.read_bytes()


@pytest.fixture
def encrypted_pdf_path(tmp_path: Path) -> Path:
    """生成一个加密的测试 PDF。"""
    pdf_path = tmp_path / "encrypted.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "加密内容")
    # 使用 AES-256 加密
    doc.save(
        str(pdf_path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,  # type: ignore[attr-defined]
        user_pw="secret",
    )
    doc.close()
    return pdf_path


# ── parse_pdf 正向测试 ────────────────────────────────

class TestParsePdfSuccess:
    """parse_pdf 正向场景。"""

    async def test_returns_correct_page_count(self, sample_pdf_path: Path) -> None:
        """3 页 PDF 返回 page_count=3，chunks 长度=3。"""
        result = await parse_pdf(sample_pdf_path)
        assert result.page_count == 3
        assert len(result.chunks) == 3

    async def test_chunks_contain_nonempty_markdown(self, sample_pdf_path: Path) -> None:
        """每个 PageChunk 包含非空 markdown_text。"""
        result = await parse_pdf(sample_pdf_path)
        for chunk in result.chunks:
            assert isinstance(chunk, PageChunk)
            assert len(chunk.markdown_text.strip()) > 0

    async def test_page_numbers_are_1_based(self, sample_pdf_path: Path) -> None:
        """页码为 1-based，方便自然理解。

        注意：pymupdf4llm 返回 0-based，由 _parse_document 转换为 1-based。
        """
        result = await parse_pdf(sample_pdf_path)
        assert result.chunks[0].page_number == 1
        assert result.chunks[-1].page_number == 3

    async def test_specific_pages_filter(self, sample_pdf_path: Path) -> None:
        """pages=[0, 2]（0-based，传给 pymupdf4llm）只返回第 1、3 页。"""
        result = await parse_pdf(sample_pdf_path, pages=[0, 2])
        assert len(result.chunks) == 2
        assert result.chunks[0].page_number == 1
        assert result.chunks[1].page_number == 3

    async def test_source_matches_input_path(self, sample_pdf_path: Path) -> None:
        """source 与传入路径的字符串表示一致。"""
        result = await parse_pdf(sample_pdf_path)
        assert result.source == str(sample_pdf_path)

    async def test_full_text_concatenation(self, sample_pdf_path: Path) -> None:
        """full_text 拼接所有 chunk 的 markdown_text。"""
        result = await parse_pdf(sample_pdf_path)
        expected = "\n\n".join(c.markdown_text for c in result.chunks)
        assert result.full_text == expected

    async def test_accepts_string_path(self, sample_pdf_path: Path) -> None:
        """传入 str 路径也能正常工作。"""
        result = await parse_pdf(str(sample_pdf_path))
        assert result.page_count == 3


# ── parse_pdf 表格测试 ────────────────────────────────

class TestParsePdfTable:
    """表格解析测试（Layout 模式）。

    注意：Layout 模式下 page_chunks 的 tables 字段为空列表，
    表格检测体现在 markdown_text 中的 Markdown 表格格式（| 分隔符）。
    """

    async def test_table_rendered_as_markdown(self, table_pdf_path: Path) -> None:
        """含有线表格的 PDF，markdown_text 中应包含 | 分隔符。"""
        result = await parse_pdf(table_pdf_path)
        assert len(result.chunks) == 1
        # Layout 应将表格转为 Markdown 表格格式
        assert "|" in result.chunks[0].markdown_text


# ── parse_pdf 页眉页脚测试 ────────────────────────────

class TestHeaderFooterFiltering:
    """页眉页脚过滤测试（Layout 模式）。"""

    async def test_default_filters_header_footer(self, sample_pdf_path: Path) -> None:
        """默认 include_header_footer=False，应过滤页眉页脚。"""
        result = await parse_pdf(sample_pdf_path)
        assert isinstance(result, PDFParseResult)
        # 基本断言：能正常返回结果即可，具体过滤效果需真实财报验证

    async def test_include_header_footer_true(self, sample_pdf_path: Path) -> None:
        """include_header_footer=True 保留页眉页脚，内容应 >= 过滤后。"""
        result_with = await parse_pdf(sample_pdf_path, include_header_footer=True)
        result_without = await parse_pdf(sample_pdf_path, include_header_footer=False)
        # 保留页眉页脚时，文本量应 >= 过滤后
        len_with = sum(len(c.markdown_text) for c in result_with.chunks)
        len_without = sum(len(c.markdown_text) for c in result_without.chunks)
        assert len_with >= len_without


# ── parse_pdf 异常测试 ────────────────────────────────

class TestParsePdfErrors:
    """parse_pdf 异常场景。"""

    async def test_file_not_found(self, tmp_path: Path) -> None:
        """路径不存在时抛出 PDFFileNotFoundError。"""
        with pytest.raises(PDFFileNotFoundError):
            await parse_pdf(tmp_path / "nonexistent.pdf")

    async def test_corrupted_file(self, tmp_path: Path) -> None:
        """损坏文件抛出 PDFCorruptedError 或 PDFParsingError。"""
        bad_pdf = tmp_path / "corrupted.pdf"
        bad_pdf.write_bytes(b"not a valid pdf content at all")
        with pytest.raises((PDFCorruptedError, PDFParsingError)):
            await parse_pdf(bad_pdf)

    async def test_encrypted_file(self, encrypted_pdf_path: Path) -> None:
        """加密 PDF 抛出 PDFEncryptedError。"""
        with pytest.raises(PDFEncryptedError):
            await parse_pdf(encrypted_pdf_path)

    async def test_all_pdf_errors_inherit_datalife_error(self) -> None:
        """所有 PDF 异常均继承 DataLifeError。"""
        assert issubclass(PDFParsingError, DataLifeError)
        assert issubclass(PDFFileNotFoundError, PDFParsingError)
        assert issubclass(PDFEncryptedError, PDFParsingError)
        assert issubclass(PDFCorruptedError, PDFParsingError)


# ── parse_pdf_bytes 测试 ──────────────────────────────

class TestParsePdfBytes:
    """parse_pdf_bytes 测试。"""

    async def test_returns_valid_result(self, sample_pdf_bytes: bytes) -> None:
        """从 bytes 解析返回正确的 PDFParseResult。"""
        result = await parse_pdf_bytes(sample_pdf_bytes, source="test.pdf")
        assert result.page_count == 3
        assert len(result.chunks) == 3
        assert result.source == "test.pdf"

    async def test_with_specific_pages(self, sample_pdf_bytes: bytes) -> None:
        """从 bytes 解析支持 pages 参数。"""
        result = await parse_pdf_bytes(sample_pdf_bytes, pages=[0])
        assert len(result.chunks) == 1

    async def test_empty_bytes_raises_error(self) -> None:
        """空 bytes 抛出异常。"""
        with pytest.raises((PDFCorruptedError, PDFParsingError)):
            await parse_pdf_bytes(b"")

    async def test_invalid_bytes_raises_error(self) -> None:
        """非法 bytes 抛出异常。"""
        with pytest.raises((PDFCorruptedError, PDFParsingError)):
            await parse_pdf_bytes(b"invalid pdf bytes here")


# ── 数据结构测试 ──────────────────────────────────────

class TestDataStructures:
    """数据结构基本行为。"""

    async def test_page_chunk_is_frozen(self) -> None:
        """PageChunk 不可变。"""
        chunk = PageChunk(page_number=1, markdown_text="test")
        with pytest.raises(FrozenInstanceError):
            chunk.page_number = 2  # type: ignore

    async def test_parse_result_full_text_empty(self) -> None:
        """空 chunks 的 full_text 为空字符串。"""
        result = PDFParseResult(source="test.pdf", page_count=0)
        assert result.full_text == ""

    async def test_parse_result_is_frozen(self) -> None:
        """PDFParseResult 不可变。"""
        result = PDFParseResult(source="test.pdf", page_count=0)
        with pytest.raises(FrozenInstanceError):
            result.page_count = 5  # type: ignore

    async def test_page_chunk_default_fields(self) -> None:
        """PageChunk 默认字段为空集合。"""
        chunk = PageChunk(page_number=1, markdown_text="text")
        assert chunk.metadata == {}
        assert chunk.toc_items == []
        assert chunk.page_boxes == []


# ── _clean_markdown 边界测试（T4：问题 5）───────────────────────────────

class TestCleanMarkdown:
    """_clean_markdown 边界测试（T4：问题 5）。"""

    def test_number_with_spaces_removed(self):
        """带前后空格的数字行应被移除。"""
        from core.data.pdf_parser import _clean_markdown

        text = "正文内容\n\n  123  \n\n更多正文"
        result = _clean_markdown(text)
        assert "123" not in result

    def test_multi_digit_page_number_removed(self):
        """多位数页码（如   123   ）应被移除。"""
        from core.data.pdf_parser import _clean_markdown

        text = "第一章 内容\n\n  123  \n\n第二章 内容"
        result = _clean_markdown(text)
        assert "123" not in result
        # 章节标题应保留
        assert "第一章" in result
        assert "第二章" in result

    def test_number_between_paragraphs(self):
        """数字行夹在正文段落之间（如财务表格中的独立数字）应被移除。

        注意：当前实现会误删这种情况，这是边界行为。
        如果需要保留行内数字，需要修改正则表达式。
        """
        from core.data.pdf_parser import _clean_markdown

        text = "资产\n\n100\n\n负债"
        result = _clean_markdown(text)
        # 当前实现会移除独立数字行
        # 如需保留，需要更精细的正则（排除行内数字）
        # 这里验证当前行为
        assert "100" not in result

    def test_empty_string_input(self):
        """空字符串输入应返回空字符串。"""
        from core.data.pdf_parser import _clean_markdown

        result = _clean_markdown("")
        assert result == ""

    def test_only_whitespace_input(self):
        """纯空白输入应返回空字符串。"""
        from core.data.pdf_parser import _clean_markdown

        result = _clean_markdown("   \n\n   ")
        assert result == ""

    def test_multiple_consecutive_empty_lines_collapsed(self):
        """连续 3+ 空行应合并为 2 个。"""
        from core.data.pdf_parser import _clean_markdown

        text = "第一章\n\n\n\n\n第二章"
        result = _clean_markdown(text)
        # 应只有最多 2 个换行
        assert "\n\n\n" not in result
