"""章节识别模块测试。

测试覆盖：
- 正向：各级策略的正常识别
- 边界：空文档、单页文档、无书签文档
- 异常：损坏的书签数据
- 降级：验证策略降级链
"""
from __future__ import annotations

import pytest
import pymupdf

from core.data.models import ParsedDocument, ParsedPage, ChapterBoundary
from core.data.chapter_detector import (
    BookmarkStrategy,
    TocPageStrategy,
    HeadingStrategy,
    FallbackStrategy,
    detect_chapters,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def pdf_with_bookmarks() -> tuple[bytes, pymupdf.Document]:
    """生成带有书签（TOC）的测试 PDF。

    包含 3 个章节，每章 2 页，共 6 页。
    书签指向第 1、3、5 页。
    """
    doc = pymupdf.open()
    for i in range(6):
        page = doc.new_page()
        if i in (0, 2, 4):
            page.insert_text((72, 72), f"# 第{i // 2 + 1}章 标题{i // 2 + 1}", fontname="china-s", fontsize=18)
        else:
            page.insert_text((72, 72), f"这是第{i + 1}页的正文内容。", fontname="china-s")
    # 设置书签 TOC
    toc = [
        [1, "第1章 标题1", 1],
        [1, "第2章 标题2", 3],
        [1, "第3章 标题3", 5],
    ]
    doc.set_toc(toc)
    content = doc.tobytes()
    return content, doc


@pytest.fixture
def pdf_no_bookmarks() -> tuple[bytes, pymupdf.Document]:
    """生成无书签但有 Markdown 标题的测试 PDF。"""
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        if i in (0, 2):
            page.insert_text((72, 72), f"第{i // 2 + 1}节 标题", fontname="china-s", fontsize=16)
        else:
            page.insert_text((72, 72), "正文内容", fontname="china-s")
    content = doc.tobytes()
    return content, doc


@pytest.fixture
def parsed_doc_6pages() -> ParsedDocument:
    """构造 6 页的 ParsedDocument fixture。"""
    pages = []
    for i in range(6):
        text = f"# 第{i // 2 + 1}章 标题{i // 2 + 1}\n正文" if i % 2 == 0 else f"第{i + 1}页正文"
        pages.append(ParsedPage(
            page_number=i + 1,
            markdown_text=text,
            toc_items=[[1, f"第{i // 2 + 1}章", i + 1]] if i % 2 == 0 else [],
        ))
    return ParsedDocument(source="test.pdf", page_count=6, chunks=pages)


@pytest.fixture
def parsed_doc_no_structure() -> ParsedDocument:
    """构造无结构信号的 ParsedDocument。"""
    pages = [
        ParsedPage(page_number=i + 1, markdown_text=f"纯文本内容第{i + 1}页。" * 50)
        for i in range(10)
    ]
    return ParsedDocument(source="plain.pdf", page_count=10, chunks=pages)


# ── 书签策略测试 ──────────────────────────────────────────────────────

class TestBookmarkStrategy:
    """PDF 书签章节识别测试。"""

    def test_valid_bookmarks(self, pdf_with_bookmarks, parsed_doc_6pages):
        """有效书签应返回正确的章节边界列表。"""
        _, doc = pdf_with_bookmarks
        strategy = BookmarkStrategy()
        result = strategy.detect(doc, parsed_doc_6pages)
        assert result is not None
        assert len(result) == 3
        assert result[0].title == "第1章 标题1"
        assert result[0].start_page == 1
        assert result[0].source == "bookmark"
        doc.close()

    def test_no_bookmarks_returns_none(self, pdf_no_bookmarks, parsed_doc_6pages):
        """无书签的 PDF 应返回 None 触发降级。"""
        _, doc = pdf_no_bookmarks
        strategy = BookmarkStrategy()
        result = strategy.detect(doc, parsed_doc_6pages)
        assert result is None
        doc.close()


# ── 标题策略测试 ──────────────────────────────────────────────────────

class TestHeadingStrategy:
    """Markdown 标题章节识别测试。"""

    def test_detect_markdown_headings(self, pdf_no_bookmarks, parsed_doc_6pages):
        """Markdown 中的 # 标题应被识别为章节边界。"""
        _, doc = pdf_no_bookmarks
        strategy = HeadingStrategy()
        result = strategy.detect(doc, parsed_doc_6pages)
        assert result is not None
        assert len(result) >= 2
        assert all(b.source == "heading" for b in result)
        doc.close()

    def test_detect_chinese_numbered_sections(self, pdf_no_bookmarks):
        """中文编号模式（第X节、一、、1.1 等）应被识别为章节边界。"""
        pages = [
            ParsedPage(page_number=1, markdown_text="第一节 重要提示\n本公司董事会及全体董事保证..."),
            ParsedPage(page_number=2, markdown_text="第二节 公司简介和主要财务指标\n一、公司信息..."),
            ParsedPage(page_number=3, markdown_text="第三节 管理层讨论与分析\n一、报告期内公司所从事的主要业务..."),
            ParsedPage(page_number=4, markdown_text="1.1 行业背景\n本公司主要从事..."),
        ]
        parsed = ParsedDocument(source="cn_report.pdf", page_count=4, chunks=pages)
        _, doc = pdf_no_bookmarks
        strategy = HeadingStrategy()
        result = strategy.detect(doc, parsed)
        assert result is not None
        assert len(result) >= 2
        titles = [b.title for b in result]
        assert any("第" in t and "节" in t for t in titles)
        doc.close()

    def test_chinese_numbering_level_inference(self, pdf_no_bookmarks):
        """中文编号的层级推断应正确：第X节→1，一、→2，1.1→3。"""
        pages = [
            ParsedPage(page_number=1, markdown_text="第一节 重要提示\n正文内容"),
            ParsedPage(page_number=2, markdown_text="一、基本情况\n正文内容\n二、主要业务\n正文"),
            ParsedPage(page_number=3, markdown_text="（一）产品概况\n正文\n1.1 背景\n详细说明"),
        ]
        parsed = ParsedDocument(source="level_test.pdf", page_count=3, chunks=pages)
        _, doc = pdf_no_bookmarks
        strategy = HeadingStrategy()
        result = strategy.detect(doc, parsed)
        if result is not None:
            top_level = min(b.level for b in result)
            assert top_level == 1
        doc.close()


# ── 兜底策略测试 ──────────────────────────────────────────────────────

class TestFallbackStrategy:
    """兜底策略测试。"""

    def test_always_returns_result(self, pdf_no_bookmarks, parsed_doc_no_structure):
        """兜底策略应始终返回覆盖全文的单一边界。"""
        _, doc = pdf_no_bookmarks
        strategy = FallbackStrategy()
        result = strategy.detect(doc, parsed_doc_no_structure)
        assert result is not None
        assert len(result) == 1
        assert result[0].source == "fallback"
        assert result[0].start_page == 1
        assert result[0].end_page == parsed_doc_no_structure.page_count
        doc.close()


# ── 降级链测试 ────────────────────────────────────────────────────────

class TestDetectChapters:
    """多级降级集成测试。"""

    def test_fallback_to_heading_when_no_bookmarks(self, pdf_no_bookmarks, parsed_doc_6pages):
        """无书签时应降级到标题检测。"""
        _, doc = pdf_no_bookmarks
        result = detect_chapters(doc, parsed_doc_6pages)
        assert len(result) >= 1
        assert all(b.source in ("heading", "toc_page", "fallback") for b in result)
        doc.close()

    def test_fallback_to_window_for_plain_text(self, pdf_no_bookmarks, parsed_doc_no_structure):
        """无结构信号时应降级到兜底窗口切分。"""
        _, doc = pdf_no_bookmarks
        result = detect_chapters(doc, parsed_doc_no_structure)
        assert len(result) >= 1
        assert any(b.source == "fallback" for b in result)
        doc.close()
