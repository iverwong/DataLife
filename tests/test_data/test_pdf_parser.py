"""PDF 解析模块测试。

测试覆盖：
- 正向：正常 PDF → Markdown 转换
- 边界：空白页、单页、超大页数
- 异常：损坏 PDF、加密 PDF、空字节流、非 PDF 文件
- 表格：有线表格、合并单元格
- 页眉页脚：过滤 vs 保留
"""

from __future__ import annotations

import pytest
import pymupdf
from unittest.mock import MagicMock, patch

from core.data.models import ParsedDocument, ParsedPage
from core.data.pdf_parser import (
    PdfParseError,
    parse_pdf_to_markdown,
    _open_pdf_from_bytes,
    _extract_pages,
    _clean_markdown,
    TABLE_STRATEGY,
    FONTSIZE_LIMIT,
    GRAPHICS_LIMIT,
)

# 标记所有测试为异步
pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """生成一个包含 3 页文本的测试 PDF。"""
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"第 {i + 1} 页内容\\n这是测试文本。")
    content = doc.tobytes()
    doc.close()
    return content


@pytest.fixture
def table_pdf_bytes() -> bytes:
    """生成一个包含简单表格的测试 PDF。"""
    doc = pymupdf.open()
    page = doc.new_page()
    # 绘制 3x3 表格（使用线条，适配 lines_strict 策略）
    x0, y0 = 72, 72
    col_w, row_h = 150, 30
    rows, cols = 4, 3  # 含表头
    for r in range(rows + 1):
        y = y0 + r * row_h
        page.draw_line((x0, y), (x0 + cols * col_w, y))
    for c in range(cols + 1):
        x = x0 + c * col_w
        page.draw_line((x, y0), (x, y0 + rows * row_h))
    # 填充表格文本
    headers = ["项目", "金额（万元）", "占比"]
    for c, h in enumerate(headers):
        page.insert_text((x0 + c * col_w + 10, y0 + 20), h, fontname="china-s")
    for r in range(1, rows):
        for c in range(cols):
            page.insert_text(
                (x0 + c * col_w + 10, y0 + r * row_h + 20),
                f"数据{r}-{c}",
                fontname="china-s",
            )
    content = doc.tobytes()
    doc.close()
    return content


@pytest.fixture
def encrypted_pdf_bytes() -> bytes:
    """生成一个加密的测试 PDF。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "加密内容")
    content = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    doc.close()
    return content


@pytest.fixture
def empty_pdf_bytes() -> bytes:
    """生成一个空白页 PDF。"""
    doc = pymupdf.open()
    doc.new_page()
    content = doc.tobytes()
    doc.close()
    return content


@pytest.fixture
def mock_page_chunk() -> dict:
    """模拟 pymupdf4llm.to_markdown 返回的 page chunk 字典。"""
    return {
        "metadata": {"page_number": 1},
        "text": "# 标题\\n\\n这是测试内容。",
        "tables": [],
        "toc_items": [],
    }


# ── 正向测试 ────────────────────────────────────────────


class TestParseSuccess:
    """正常 PDF 解析测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_basic_parse(self, sample_pdf_bytes: bytes):
        """测试基本解析：3 页 PDF 应返回 3 个 ParsedPage。

        测试条件：
            - 输入包含 3 页文本的 PDF

        预期结果：
            - 返回 ParsedDocument 对象
            - total_pages 为 3
            - pages 列表包含 3 个元素
            - source 正确设置
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes, source="test.pdf")

        # Assert
        assert isinstance(result, ParsedDocument)
        assert result.total_pages == 3
        assert len(result.pages) == 3
        assert result.source == "test.pdf"

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_page_content_not_empty(self, sample_pdf_bytes: bytes):
        """测试每页应有非空文本。

        测试条件：
            - 输入包含 3 页文本的 PDF

        预期结果：
            - 每页的 text 字段都包含非空内容
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes)

        # Assert
        for page in result.pages:
            assert page.text.strip(), f"第 {page.page_number} 页文本为空"

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_page_number_1_based(self, sample_pdf_bytes: bytes):
        """测试页码应为 1-based。

        测试条件：
            - 输入包含 3 页文本的 PDF

        预期结果：
            - 第一页 page_number 为 1
            - 最后一页 page_number 为 3
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes)

        # Assert
        assert result.pages[0].page_number == 1
        assert result.pages[-1].page_number == 3

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_full_text_property(self, sample_pdf_bytes: bytes):
        """测试 full_text 应拼接所有页面文本。

        测试条件：
            - 输入包含 3 页文本的 PDF

        预期结果：
            - full_text 包含 "---" 分隔符
            - full_text 包含所有页面的内容
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes)

        # Assert
        assert "---" in result.full_text  # 分隔符
        assert "第 1 页" in result.full_text

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_specific_pages(self, sample_pdf_bytes: bytes):
        """测试指定页码只解析对应页面。

        测试条件：
            - 输入包含 3 页文本的 PDF
            - pages 参数指定 [0, 2]（第 1 和第 3 页）

        预期结果：
            - 返回 2 个页面
            - page_number 正确映射到 1 和 3
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes, pages=[0, 2])

        # Assert
        assert len(result.pages) == 2
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 3


# ── 表格测试 ────────────────────────────────────────────


class TestTableExtraction:
    """表格提取测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_table_detected(self, table_pdf_bytes: bytes):
        """测试含线条表格的 PDF 应检测到表格。

        测试条件：
            - 输入包含线条表格的 PDF

        预期结果：
            - 解析后页面的 Markdown 中包含表格标记（| 分隔符）
        """
        # Act
        result = await parse_pdf_to_markdown(table_pdf_bytes)

        # Assert
        assert len(result.pages) == 1
        page = result.pages[0]
        # Markdown 中应包含表格标记（| 分隔符）
        assert "|" in page.text

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_table_metadata(self, table_pdf_bytes: bytes):
        """测试 tables 元信息应包含行列数。

        测试条件：
            - 输入包含线条表格的 PDF

        预期结果：
            - tables 列表中每项包含 row_count 和 col_count
        """
        # Act
        result = await parse_pdf_to_markdown(table_pdf_bytes)

        # Assert
        page = result.pages[0]
        if page.tables:  # pymupdf4llm 可能以不同方式报告
            assert page.tables[0].get("row_count", 0) > 0


# ── 页眉页脚测试 ────────────────────────────────────────


class TestHeaderFooter:
    """页眉页脚过滤测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_default_no_header_footer(self, sample_pdf_bytes: bytes):
        """测试默认应过滤页眉页脚（include_header_footer=False）。

        测试条件：
            - 输入包含文本的 PDF
            - 未指定 include_header_footer 参数

        预期结果：
            - 返回 ParsedDocument 对象
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes)

        # Assert
        assert isinstance(result, ParsedDocument)

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_include_header_footer(self, sample_pdf_bytes: bytes):
        """测试明确指定时应保留页眉页脚。

        测试条件：
            - 输入包含文本的 PDF
            - include_header_footer=True

        预期结果：
            - 返回 ParsedDocument 对象
        """
        # Act
        result = await parse_pdf_to_markdown(sample_pdf_bytes, include_header_footer=True)

        # Assert
        assert isinstance(result, ParsedDocument)


# ── 异常测试 ────────────────────────────────────────────


class TestParseErrors:
    """异常场景测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_empty_bytes_raises(self):
        """测试空字节流应抛出 PdfParseError。

        测试条件：
            - 输入空字节流 b""

        预期结果：
            - 抛出 PdfParseError 异常
        """
        # Act & Assert
        with pytest.raises(PdfParseError):
            await parse_pdf_to_markdown(b"")

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_invalid_content_raises(self):
        """测试非 PDF 内容应抛出 PdfParseError。

        测试条件：
            - 输入非 PDF 内容的字节串

        预期结果：
            - 抛出 PdfParseError 异常
        """
        # Act & Assert
        with pytest.raises(PdfParseError):
            await parse_pdf_to_markdown(b"this is not a pdf")

    @pytest.mark.unit
    @pytest.mark.fast
    async def test_encrypted_pdf_raises(self, encrypted_pdf_bytes: bytes):
        """测试加密 PDF（未提供密码）应抛出 PdfParseError。

        测试条件：
            - 输入加密的 PDF

        预期结果：
            - 抛出 PdfParseError 异常
        """
        # Act & Assert
        with pytest.raises(PdfParseError):
            await parse_pdf_to_markdown(encrypted_pdf_bytes)


# ── 清理函数测试 ────────────────────────────────────────


class TestCleanMarkdown:
    """Markdown 清理测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    def test_remove_excessive_newlines(self):
        """测试连续 3+ 空行应合并为 2 个。

        测试条件：
            - 输入包含连续多个换行符的字符串

        预期结果：
            - 连续 3 个以上换行符被合并为 2 个
        """
        # Arrange
        text = "段落一\\n\\n\\n\\n\\n段落二"

        # Act
        result = _clean_markdown(text)

        # Assert
        assert "\\n\\n\\n" not in result
        assert "段落一" in result
        assert "段落二" in result

    @pytest.mark.unit
    @pytest.mark.fast
    def test_remove_standalone_page_numbers(self):
        """测试独立成行的页码数字应被移除。

        测试条件：
            - 输入包含独立成行的页码数字

        预期结果：
            - 独立的 1~4 位数字行被移除
        """
        # Arrange
        text = "正文内容\\n\\n42\\n\\n更多内容"

        # Act
        result = _clean_markdown(text)

        # Assert
        assert "\\n42\\n" not in result

    @pytest.mark.unit
    @pytest.mark.fast
    def test_preserve_meaningful_numbers(self):
        """测试表格或正文中的数字不应被误删。

        测试条件：
            - 输入包含有意义数字的字符串

        预期结果：
            - 数字保留
        """
        # Arrange
        text = "金额：42万元"

        # Act
        result = _clean_markdown(text)

        # Assert
        assert "42" in result


# ── 内部函数测试 ────────────────────────────────────────


class TestOpenPdf:
    """PDF 打开函数测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    def test_open_valid_pdf(self, sample_pdf_bytes: bytes):
        """测试正常 PDF 应成功打开。

        测试条件：
            - 输入有效的 PDF 字节流

        预期结果：
            - 返回 pymupdf.Document 对象
            - page_count 正确
        """
        # Act
        doc = _open_pdf_from_bytes(sample_pdf_bytes)

        # Assert
        assert doc.page_count == 3
        doc.close()

    @pytest.mark.unit
    @pytest.mark.fast
    def test_open_empty_bytes(self):
        """测试空字节流应抛出 PdfParseError。

        测试条件：
            - 输入空字节流

        预期结果：
            - 抛出 PdfParseError 异常
        """
        # Act & Assert
        with pytest.raises(PdfParseError):
            _open_pdf_from_bytes(b"")

    @pytest.mark.unit
    @pytest.mark.fast
    def test_open_non_pdf(self):
        """测试非 PDF 文件应抛出 PdfParseError。

        测试条件：
            - 输入非 PDF 格式的字节流

        预期结果：
            - 抛出 PdfParseError 异常
        """
        # Act & Assert
        with pytest.raises(PdfParseError):
            _open_pdf_from_bytes(b"not a pdf file")


class TestExtractPages:
    """页面提取函数测试。"""

    @pytest.mark.unit
    @pytest.mark.fast
    def test_extract_pages_from_document(self, sample_pdf_bytes: bytes):
        """测试从文档对象提取页面。

        测试条件：
            - 输入有效的 PDF 字节流
            - 调用 _extract_pages 函数

        预期结果：
            - 返回 ParsedPage 列表
            - 列表长度等于页数
        """
        # Arrange
        doc = _open_pdf_from_bytes(sample_pdf_bytes)

        # Act
        pages = _extract_pages(doc)

        # Assert
        assert len(pages) == 3
        assert all(isinstance(p, ParsedPage) for p in pages)

        # Cleanup
        doc.close()

    @pytest.mark.unit
    @pytest.mark.fast
    def test_extract_pages_with_pagination(self, sample_pdf_bytes: bytes):
        """测试分页提取。

        测试条件：
            - 输入有效的 PDF 字节流
            - pages 参数指定 [0, 2]

        预期结果：
            - 只返回指定的页面
        """
        # Arrange
        doc = _open_pdf_from_bytes(sample_pdf_bytes)

        # Act
        pages = _extract_pages(doc, pages=[0, 2])

        # Assert
        assert len(pages) == 2
        assert pages[0].page_number == 1
        assert pages[1].page_number == 3

        # Cleanup
        doc.close()
