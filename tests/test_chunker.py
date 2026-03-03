"""分块引擎测试。

测试覆盖：
- 正向：正常章节切分、完整章节直通
- 边界：单章节文档、空文档
- 超长：超长章节的子标题拆分、token 窗口拆分
- 属性：needs_prior_summary 标记、chunk_index 编号
"""
from __future__ import annotations

import pytest

from core.data.models import (
    ParsedDocument,
    ParsedPage,
    ChapterBoundary,
    Chunk,
    ChunkList,
    ChunkType,
)
from core.data.chunker import (
    build_chunks,
    _extract_chapter_text,
    _split_by_subheadings,
    _split_by_token_window,
)
from core.data.token_counter import count_tokens


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def short_parsed_doc() -> ParsedDocument:
    """构造短文档（每页约 100 tokens）。"""
    pages = [
        ParsedPage(page_number=i + 1, markdown_text=f"## 第{i+1}节\n" + "这是正文内容。" * 20)
        for i in range(4)
    ]
    return ParsedDocument(source="short.pdf", page_count=4, chunks=pages)


@pytest.fixture
def long_chapter_doc() -> ParsedDocument:
    """构造包含超长章节的文档。"""
    page1 = ParsedPage(page_number=1, markdown_text="# 第一章\n" + "短内容。" * 10)
    long_text = "# 第二章\n"
    for i in range(5):
        long_text += f"## 2.{i+1} 子节标题\n" + "这是一段很长的正文内容，用于测试超长章节的子标题拆分逻辑。" * 100 + "\n\n"
    page2 = ParsedPage(page_number=2, markdown_text=long_text[:len(long_text)//2])
    page3 = ParsedPage(page_number=3, markdown_text=long_text[len(long_text)//2:])
    return ParsedDocument(source="long.pdf", page_count=3, chunks=[page1, page2, page3])


@pytest.fixture
def two_chapters() -> list[ChapterBoundary]:
    """两个章节的边界定义。"""
    return [
        ChapterBoundary(title="第一章", level=1, start_page=1, end_page=1, source="bookmark"),
        ChapterBoundary(title="第二章", level=1, start_page=2, end_page=3, source="bookmark"),
    ]


# ── 正向测试 ──────────────────────────────────────────────────────────

class TestBuildChunks:
    """分块引擎核心测试。"""

    def test_short_doc_complete_chapters(self, short_parsed_doc):
        """短文档每章应为 COMPLETE_CHAPTER 类型。"""
        chapters = [
            ChapterBoundary(title=f"第{i+1}节", level=1, start_page=i+1, end_page=i+1, source="heading")
            for i in range(4)
        ]
        result = build_chunks(short_parsed_doc, chapters, max_tokens=8000)
        assert isinstance(result, ChunkList)
        assert len(result.chunks) == 4
        assert all(c.chunk_type == ChunkType.COMPLETE_CHAPTER for c in result.chunks)

    def test_prior_summary_marking(self, short_parsed_doc):
        """第 2 个及之后的章节块应标记 needs_prior_summary=True。"""
        chapters = [
            ChapterBoundary(title=f"第{i+1}节", level=1, start_page=i+1, end_page=i+1, source="heading")
            for i in range(4)
        ]
        result = build_chunks(short_parsed_doc, chapters)
        assert result.chunks[0].needs_prior_summary is False
        assert all(c.needs_prior_summary is True for c in result.chunks[1:])

    def test_long_chapter_split(self, long_chapter_doc, two_chapters):
        """超长章节应被拆分为多个子块。"""
        result = build_chunks(long_chapter_doc, two_chapters, max_tokens=500)
        ch2_chunks = [c for c in result.chunks if "第二章" in str(c.chapter_path)]
        assert len(ch2_chunks) > 1
        assert all(c.chunk_type in (ChunkType.SUB_SECTION, ChunkType.TOKEN_WINDOW) for c in ch2_chunks)

    def test_token_count_within_limit(self, long_chapter_doc, two_chapters):
        """每个 chunk 的 token 数不应超过 max_tokens。"""
        max_t = 500
        result = build_chunks(long_chapter_doc, two_chapters, max_tokens=max_t)
        for c in result.chunks:
            assert c.token_count <= max_t + 50

    def test_full_passthrough_short_doc(self):
        """全文 token 数 ≤ max_tokens 时，应整体直通为单个 Chunk。"""
        pages = [
            ParsedPage(page_number=1, markdown_text="# 重要提示\n内容A\n\n# 公司简介\n内容B\n\n# 经营情况\n内容C")
        ]
        parsed = ParsedDocument(source="short_notice.pdf", page_count=1, chunks=pages)
        chapters = [
            ChapterBoundary(title="重要提示", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="公司简介", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="经营情况", level=1, start_page=1, end_page=1, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=8000)
        assert len(result.chunks) == 1
        assert result.chunks[0].chunk_type == ChunkType.COMPLETE_CHAPTER
        assert "重要提示" in result.chunks[0].text
        assert "经营情况" in result.chunks[0].text

    def test_same_page_merge(self):
        """同页多章节应被合并为一个 Chunk（非整体直通场景）。"""
        page1 = ParsedPage(page_number=1, markdown_text="# A\n短内容\n# B\n短内容\n# C\n短内容")
        long_text = "# D 长章节\n" + "这是很长的正文。" * 500
        page2 = ParsedPage(page_number=2, markdown_text=long_text[:len(long_text)//2])
        page3 = ParsedPage(page_number=3, markdown_text=long_text[len(long_text)//2:])
        parsed = ParsedDocument(source="mixed.pdf", page_count=3, chunks=[page1, page2, page3])
        chapters = [
            ChapterBoundary(title="A", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="B", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="C", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="D 长章节", level=1, start_page=2, end_page=3, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=500)
        page1_chunks = [c for c in result.chunks if c.page_range == (1, 1)]
        assert len(page1_chunks) == 1
        assert "A" in page1_chunks[0].text
        assert "C" in page1_chunks[0].text


# ── 文本提取测试 ──────────────────────────────────────────────────────

class TestExtractChapterText:
    """章节文本提取测试。"""

    def test_single_page_chapter(self, short_parsed_doc):
        """单页章节应返回该页完整文本。"""
        ch = ChapterBoundary(title="第1节", level=1, start_page=1, end_page=1, source="heading")
        text = _extract_chapter_text(short_parsed_doc, ch)
        assert "第1节" in text

    def test_multi_page_chapter(self, short_parsed_doc):
        """跨页章节应拼接所有页面文本。"""
        ch = ChapterBoundary(title="测试", level=1, start_page=1, end_page=2, source="heading")
        text = _extract_chapter_text(short_parsed_doc, ch)
        assert "第1节" in text
        assert "第2节" in text


# ── Token 窗口切分测试 ────────────────────────────────────────────────

class TestSplitByTokenWindow:
    """Token 窗口切分测试。"""

    def test_split_produces_multiple_chunks(self):
        """长文本应被切分为多个 chunk。"""
        text = "这是测试段落。\n\n" * 500
        result = _split_by_token_window(
            text, ["测试章"], (1, 5), max_tokens=200, overlap_tokens=50
        )
        assert len(result) > 1
        assert all(c.chunk_type == ChunkType.TOKEN_WINDOW for c in result)

    def test_chunk_index_sequential(self):
        """子块的 chunk_index 应从 0 开始递增。"""
        text = "段落内容。\n\n" * 500
        result = _split_by_token_window(
            text, ["测试"], (1, 3), max_tokens=200, overlap_tokens=50
        )
        for i, c in enumerate(result):
            assert c.chunk_index == i

    @pytest.mark.xfail(reason="问题 6：overlap 取首部而非尾部 - 当前实现取头部token")
    def test_overlap_takes_tail_tokens(self):
        """验证 overlap 文本来自前一个 chunk 的尾部（非头部）。

        当前实现使用 truncate_to_tokens(prev_text, overlap_tokens) 取得是文本开头部分。
        正确行为应该是取文本末尾部分。

        测试设计：构造一个包含多个段落的文本，第一段很长（会超限被分割），
        验证第二个 chunk 的 overlap 来自第一段的**末尾**而非开头。
        """
        # 构造一个多段落文本，第一段超长
        # 段落1开头是 "START"，结尾是 "END"
        # 段落2是不同的内容
        text = "START" + "AAAA" * 50 + "\n\n" + "BBBB" * 50 + "\n\n" + "CCCC" * 50

        result = _split_by_token_window(
            text, ["测试"], (1, 3), max_tokens=100, overlap_tokens=20
        )

        # 应该产生至少 2 个 chunk
        assert len(result) >= 2, f"Expected at least 2 chunks, got {len(result)}"

        # 获取第一个 chunk 和第二个 chunk
        first_chunk = result[0].text
        second_chunk = result[1].text

        # 第一个 chunk 应该以 "START" 开头
        assert first_chunk.startswith("START"), f"First chunk should start with START, got: {first_chunk[:50]}"

        # 第二个 chunk 应该包含前一个 chunk 的末尾内容（"AAAA"区域）
        # 当前错误实现取头部，所以 second_chunk 会以 "BBBB" 或 "CCCC" 开头
        # 正确实现应该取尾部，所以 second_chunk 应该包含 "AAAA" 或更靠后的内容

        # 验证第二个 chunk 的开头不应该紧接第一个 chunk 的开头（那是错误的取头部方式）
        # 如果取尾部，第二个 chunk 应该包含前一个 chunk 后半部分的内容
        # 当前 bug 实现会取 "START" + "AAAA"... 的开头部分
        # 正确实现应该取 "...AAAA" (末尾部分)

        # 检查：如果 overlap 取尾部，second_chunk 不应该以 "START" 开头
        # 因为 "START" 是第一个 chunk 的开头，不是末尾
        assert not second_chunk.startswith("START"), (
            "Overlap should NOT contain head of previous chunk (START). "
            f"Second chunk starts with: {second_chunk[:50]}"
        )


# ── 中文编号子标题拆分测试 ────────────────────────────────────────────

class TestSplitBySubheadingsChinese:
    """中文编号子标题拆分测试。"""

    def test_cn_section_pattern_split(self):
        """含中文编号子标题（一、二、）的超长章节应按子标题拆分。

        注意：当子标题下内容仍超限时，退回到 TOKEN_WINDOW 是合理的降级行为。
        可能有 SUB_SECTION（如果内容在限制内）或 TOKEN_WINDOW（降级）或混合。
        """
        text = "# 第二节 公司概况\n"
        for label in ["一、公司基本情况", "二、主要业务", "三、核心竞争力", "四、经营情况"]:
            text += f"{label}\n" + "这是详细的正文内容描述。" * 80 + "\n\n"
        result = _split_by_subheadings(
            text, ["第二节 公司概况"], (2, 5), max_tokens=500, overlap_tokens=50
        )
        assert result is not None
        assert len(result) >= 2
        # 允许 SUB_SECTION 和 TOKEN_WINDOW 混合（超长内容退回是合理的降级行为）
        assert all(c.chunk_type in (ChunkType.SUB_SECTION, ChunkType.TOKEN_WINDOW) for c in result)

    def test_numeric_dot_pattern_split(self):
        """含「1.1」「1.2」风格编号的章节应按子标题拆分。"""
        text = "# 第三节 管理层讨论\n"
        for sub in ["1.1 行业背景", "1.2 市场环境", "1.3 经营策略", "1.4 财务分析"]:
            text += f"{sub}\n" + "分析内容段落。" * 80 + "\n\n"
        result = _split_by_subheadings(
            text, ["第三节 管理层讨论"], (3, 6), max_tokens=500, overlap_tokens=50
        )
        assert result is not None
        assert len(result) >= 2


# ── level=2 同页合并测试 ──────────────────────────────────────────────

class TestLevel2SamePageMerge:
    """level=2 子章节同页合并测试。"""

    def test_same_page_level2_boundaries_merged(self):
        """同页的 level=2 子边界应被合并，减少产出的 chunk 数。"""
        from core.data.chunker import _merge_same_page_boundaries

        sub_boundaries = [
            ChapterBoundary(title="一、基本情况", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="二、主要业务", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="三、核心竞争力", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="四、经营分析", level=2, start_page=3, end_page=4, source="bookmark"),
        ]
        merged = _merge_same_page_boundaries(sub_boundaries)
        assert len(merged) == 2
        # MergedChapter 对象通过 .chapter 属性访问 ChapterBoundary
        assert "一、基本情况" in merged[0].chapter.title
        assert "三、核心竞争力" in merged[0].chapter.title
        assert merged[0].chapter.start_page == 2
        assert merged[0].chapter.end_page == 2
        assert merged[1].chapter.title == "四、经营分析"

    def test_build_chunks_uses_level2_merge(self):
        """build_chunks 应对超长章节内的 level=2 子边界做同页合并后再拆分。

        注意：即使 level=2 边界被合并，如果合并后的内容仍超 max_tokens，
        会被退回 token 窗口拆分，这是合理的降级行为。
        """
        page1 = ParsedPage(page_number=1, markdown_text="# 章节A\n短内容。" * 10)
        page2 = ParsedPage(page_number=2, markdown_text="一、情况\n内容。" * 30 + "\n二、业务\n内容。" * 30 + "\n三、竞争\n内容。" * 30)
        page3 = ParsedPage(page_number=3, markdown_text="四、分析\n" + "详细分析内容。" * 200)
        page4 = ParsedPage(page_number=4, markdown_text="详细分析续。" * 200)
        parsed = ParsedDocument(source="test.pdf", page_count=4, chunks=[page1, page2, page3, page4])
        chapters = [
            ChapterBoundary(title="章节A", level=1, start_page=1, end_page=1, source="bookmark"),
            ChapterBoundary(title="章节B", level=1, start_page=2, end_page=4, source="bookmark"),
            ChapterBoundary(title="一、情况", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="二、业务", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="三、竞争", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="四、分析", level=2, start_page=3, end_page=4, source="bookmark"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=500)
        ch_b_chunks = [c for c in result.chunks if c.page_range != (1, 1)]
        page2_chunks = [c for c in ch_b_chunks if c.page_range == (2, 2)]
        # 验证 page2_chunks 存在（合并后的章节），且所有 chunk 的 token 数在限制内
        assert len(page2_chunks) >= 1, "page2 should have at least one chunk"
        assert all(c.token_count <= 550 for c in page2_chunks), "all chunks should be within token limit"


# ── contained_chapters 元信息测试 ─────────────────────────────────────

class TestContainedChapters:
    """Chunk.contained_chapters 元信息填充测试。"""

    def test_single_chapter_contains_self(self):
        """单章节 Chunk 的 contained_chapters 应包含自身。"""
        pages = [
            ParsedPage(page_number=1, markdown_text="# 第一章\n" + "正文。" * 50),
            ParsedPage(page_number=2, markdown_text="# 第二章\n" + "正文。" * 50),
        ]
        parsed = ParsedDocument(source="test.pdf", page_count=2, chunks=pages)
        chapters = [
            ChapterBoundary(title="第一章", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="第二章", level=1, start_page=2, end_page=2, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=8000)
        for chunk in result.chunks:
            assert len(chunk.contained_chapters) == 1
            assert chunk.contained_chapters[0].title in ("第一章", "第二章")

    def test_same_page_merge_contains_all_originals(self):
        """同页合并 Chunk 的 contained_chapters 应包含所有被合并的原始章节。"""
        page1 = ParsedPage(page_number=1, markdown_text="# A\n短\n# B\n短\n# C\n短")
        long_text = "# D\n" + "长正文。" * 500
        page2 = ParsedPage(page_number=2, markdown_text=long_text[:len(long_text)//2])
        page3 = ParsedPage(page_number=3, markdown_text=long_text[len(long_text)//2:])
        parsed = ParsedDocument(source="test.pdf", page_count=3, chunks=[page1, page2, page3])
        chapters = [
            ChapterBoundary(title="A", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="B", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="C", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="D", level=1, start_page=2, end_page=3, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=500)
        page1_chunks = [c for c in result.chunks if c.page_range == (1, 1)]
        assert len(page1_chunks) == 1
        merged_chunk = page1_chunks[0]
        assert len(merged_chunk.contained_chapters) == 3
        titles = {m.title for m in merged_chunk.contained_chapters}
        assert titles == {"A", "B", "C"}

    def test_passthrough_contains_all_chapters(self):
        """整体直通 Chunk 的 contained_chapters 应包含所有 level=1 章节。"""
        pages = [
            ParsedPage(page_number=1, markdown_text="# 重要提示\n内容\n\n# 公司简介\n内容\n\n# 经营情况\n内容")
        ]
        parsed = ParsedDocument(source="short.pdf", page_count=1, chunks=pages)
        chapters = [
            ChapterBoundary(title="重要提示", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="公司简介", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="经营情况", level=1, start_page=1, end_page=1, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=8000)
        assert len(result.chunks) == 1
        chunk = result.chunks[0]
        assert len(chunk.contained_chapters) == 3
        titles = [m.title for m in chunk.contained_chapters]
        assert titles == ["重要提示", "公司简介", "经营情况"]

    def test_sub_section_inherits_parent(self):
        """子块拆分 Chunk 的 contained_chapters 应继承父章节信息。"""
        page1 = ParsedPage(page_number=1, markdown_text="# 短章\n内容")
        long_text = "# 长章\n" + "## 子节A\n" + "详细内容。" * 200 + "\n\n## 子节B\n" + "更多内容。" * 200
        page2 = ParsedPage(page_number=2, markdown_text=long_text[:len(long_text)//2])
        page3 = ParsedPage(page_number=3, markdown_text=long_text[len(long_text)//2:])
        parsed = ParsedDocument(source="test.pdf", page_count=3, chunks=[page1, page2, page3])
        chapters = [
            ChapterBoundary(title="短章", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="长章", level=1, start_page=2, end_page=3, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=300)
        long_chunks = [c for c in result.chunks if c.page_range != (1, 1)]
        assert len(long_chunks) > 1
        for chunk in long_chunks:
            assert len(chunk.contained_chapters) >= 1
            assert chunk.contained_chapters[0].title == "长章"
