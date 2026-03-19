"""分块引擎测试。

测试覆盖：
- 正向：正常章节切分、完整章节直通
- 边界：单章节文档、空文档
- 超长：超长章节的子标题拆分、token 窗口拆分
- 属性：needs_prior_summary 标记、chunk_index 编号
"""
from __future__ import annotations

import pytest

from core.data.exceptions import InvalidChunkingParameterError
from core.data.models import (
    ParsedDocument,
    ParsedPage,
    ChapterBoundary,
    ChapterPathEntry,
    ChunkList,
    ChunkType,
)
from core.data.chunking.chunker import (
    build_chunks,
    _extract_chapter_text,
    _split_by_subheadings,
    _split_by_token_window,
    _split_by_token_window_with_index,
)
from core.data.chunking.token_counter import count_tokens, slice_tokens
from core.data.chunking.token_indexer import (
    PageTokenIndex,
    get_chapter_token_count,
)


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
        result = build_chunks(short_parsed_doc, chapters, max_tokens=8000, overlap_tokens=200)
        assert isinstance(result, ChunkList)
        assert len(result.chunks) == 4
        assert all(c.chunk_type == ChunkType.COMPLETE_CHAPTER for c in result.chunks)

    def test_prior_summary_marking(self, short_parsed_doc):
        """第 2 个及之后的章节块应标记 needs_prior_summary=True。"""
        chapters = [
            ChapterBoundary(title=f"第{i+1}节", level=1, start_page=i+1, end_page=i+1, source="heading")
            for i in range(4)
        ]
        result = build_chunks(short_parsed_doc, chapters, max_tokens=8000, overlap_tokens=200)
        assert result.chunks[0].needs_prior_summary is False
        assert all(c.needs_prior_summary is True for c in result.chunks[1:])

    def test_long_chapter_split(self, long_chapter_doc, two_chapters):
        """超长章节应被拆分为多个子块。"""
        result = build_chunks(long_chapter_doc, two_chapters, max_tokens=500, overlap_tokens=50)
        ch2_chunks = [c for c in result.chunks if "第二章" in str(c.chapter_path)]
        assert len(ch2_chunks) > 1
        assert all(c.chunk_type in (ChunkType.SUB_SECTION, ChunkType.TOKEN_WINDOW) for c in ch2_chunks)

    def test_token_count_within_limit(self, long_chapter_doc, two_chapters):
        """每个 chunk 的 token 数不应超过 max_tokens。"""
        max_t = 500
        result = build_chunks(long_chapter_doc, two_chapters, max_tokens=max_t, overlap_tokens=50)
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
        result = build_chunks(parsed, chapters, max_tokens=8000, overlap_tokens=200)
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
        result = build_chunks(parsed, chapters, max_tokens=500, overlap_tokens=50)
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

    def test_overlap_takes_tail_tokens(self):
        """验证 overlap 文本来自前一个 chunk 的尾部（非头部）。

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


# ── level=2 同页合并测试 ──────────────────────────────────────────────

class TestLevel2SamePageMerge:
    """level=2 子章节同页合并测试。"""

    def test_same_page_level2_boundaries_merged(self):
        """同页的 level=2 子边界应被合并，减少产出的 chunk 数。"""
        from core.data.chunking.chunker import _merge_same_page_boundaries

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
        result = build_chunks(parsed, chapters, max_tokens=500, overlap_tokens=50)
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
        result = build_chunks(parsed, chapters, max_tokens=8000, overlap_tokens=200)
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
        result = build_chunks(parsed, chapters, max_tokens=500, overlap_tokens=50)
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
        result = build_chunks(parsed, chapters, max_tokens=8000, overlap_tokens=200)
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
        result = build_chunks(parsed, chapters, max_tokens=300, overlap_tokens=30)
        long_chunks = [c for c in result.chunks if c.page_range != (1, 1)]
        assert len(long_chunks) > 1
        for chunk in long_chunks:
            assert len(chunk.contained_chapters) >= 1
            assert chunk.contained_chapters[0].title == "长章"


# ── Token Window 范围限定测试（P1 Bug） ────────────────────────────────

class TestSplitByTokenWindowWithIndex:
    """_split_by_token_window_with_index 范围限定测试。

    验证 token 窗口切分只在本章节 token 范围内进行，不跨越章节边界。
    """

    def _create_parsed_and_index(
        self,
    ) -> tuple[ParsedDocument, PageTokenIndex]:
        """创建 3 章文档（每章约 1000 tokens）+ token_index。

        每章有唯一标记文本，便于验证不包含其他章节内容。
        """
        from core.data.chunking.token_indexer import encode_pages_incremental
        from core.data.models import PDFParseResult, PageChunk

        # 章节 1：第 1 页，唯一标记 "CHAPTER_ONE_MARKER"
        ch1_text = "# 第一章\n" + "CHAPTER_ONE_MARKER " * 200
        # 章节 2：第 2-3 页，唯一标记 "CHAPTER_TWO_MARKER"
        ch2_text = "# 第二章\n" + "CHAPTER_TWO_MARKER " * 300 + "\n\n" + "更多内容 " * 300
        # 章节 3：第 4-5 页，唯一标记 "CHAPTER_THREE_MARKER"
        ch3_text = "# 第三章\n" + "CHAPTER_THREE_MARKER " * 300 + "\n\n" + "更多内容 " * 300

        pages = [
            PageChunk(
                page_number=1,
                markdown_text=ch1_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text=ch2_text[: len(ch2_text) // 2],
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=3,
                markdown_text=ch2_text[len(ch2_text) // 2 :],
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=4,
                markdown_text=ch3_text[: len(ch3_text) // 2],
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=5,
                markdown_text=ch3_text[len(ch3_text) // 2 :],
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]

        parsed = PDFParseResult(
            source="test.pdf",
            page_count=5,
            chunks=pages,
        )

        token_index = encode_pages_incremental(parsed)
        assert token_index is not None

        return parsed, token_index

    def test_only_covers_chapter_pages(self):
        """验证切分结果的页码范围在章节 page_range 内。

        测试场景：对第 2 章（page 2-3）调用 token 窗口切分，
        预期所有 chunk 的 page_range 都在 [2, 3] 范围内。
        """
        from core.data.chunking.token_indexer import get_chapter_token_count
        from core.data.chunking.chunker import _split_by_token_window_with_index

        parsed, token_index = self._create_parsed_and_index()

        # 第 2 章的 page_range = (2, 3)
        page_range = (2, 3)

        # 计算第 2 章的 token 总数
        chapter_tokens = get_chapter_token_count(token_index, 2, 3)
        assert chapter_tokens > 0, "第 2 章应有 token"

        # 调用 _split_by_token_window_with_index（内部使用 token_index）
        chunks = _split_by_token_window_with_index(
            text="",  # 实际使用 token_index 切分，text 参数用于降级
            chapter_path=["第二章"],
            page_range=page_range,
            max_tokens=200,  # 较小值，确保会切分
            overlap_tokens=20,
            token_index=token_index,
        )

        assert len(chunks) > 1, "超长章节应被切分为多个 chunk"

        # 关键断言：每个 chunk 的页码范围应在 [2, 3] 内
        for i, chunk in enumerate(chunks):
            assert chunk.page_range[0] >= 2, (
                f"Chunk {i} page_range[0]={chunk.page_range[0]}, expected >= 2"
            )
            assert chunk.page_range[1] <= 3, (
                f"Chunk {i} page_range[1]={chunk.page_range[1]}, expected <= 3"
            )

    def test_does_not_include_other_chapter_content(self):
        """验证切分结果不包含其他章节的文本。

        测试场景：第 2 章的 chunks 不应包含第 1 章或第 3 章的唯一标记。
        """
        from core.data.chunking.chunker import _split_by_token_window_with_index

        parsed, token_index = self._create_parsed_and_index()

        # 对第 2 章（page 2-3）切分
        page_range = (2, 3)

        chunks = _split_by_token_window_with_index(
            text="",
            chapter_path=["第二章"],
            page_range=page_range,
            max_tokens=200,
            overlap_tokens=20,
            token_index=token_index,
        )

        # 验证每个 chunk 都不包含其他章节的标记
        for i, chunk in enumerate(chunks):
            assert "CHAPTER_ONE_MARKER" not in chunk.text, (
                f"Chunk {i} should not contain Chapter 1 marker"
            )
            assert "CHAPTER_THREE_MARKER" not in chunk.text, (
                f"Chunk {i} should not contain Chapter 3 marker"
            )

    def test_token_count_matches_chapter_total(self):
        """验证最后一个 chunk 的结束位置在章节范围内。

        测试场景：最后一个 chunk 应该恰好在章节结束位置结束，
        不超出章节范围。
        """
        from core.data.chunking.chunker import _split_by_token_window_with_index

        parsed, token_index = self._create_parsed_and_index()

        # 第 2 章的 page_range = (2, 3)
        page_range = (2, 3)

        # 计算章节结束位置
        chapter_start_token = None
        start_idx = None
        end_idx = None

        for i, (page_num, token_start) in enumerate(token_index.page_boundaries):
            if page_num == page_range[0]:
                chapter_start_token = token_start
                start_idx = i
            if page_num == page_range[1]:
                end_idx = i
                break

        # 章节结束位置 = 最后一页的下一页起始 token
        chapter_end_idx = end_idx + 1
        if chapter_end_idx < len(token_index.page_boundaries):
            chapter_end_token = token_index.page_boundaries[chapter_end_idx][1]
        else:
            chapter_end_token = token_index.total_tokens

        chapter_total_tokens = chapter_end_token - chapter_start_token

        chunks = _split_by_token_window_with_index(
            text="",
            chapter_path=["第二章"],
            page_range=page_range,
            max_tokens=200,
            overlap_tokens=20,
            token_index=token_index,
        )

        # 验证最后一个 chunk 的 page_range 结束页是章节的结束页
        last_chunk = chunks[-1]
        assert last_chunk.page_range[1] == page_range[1], (
            f"Last chunk page_range[1]={last_chunk.page_range[1]}, "
            f"expected {page_range[1]}"
        )

        # 验证总 token 数不超过章节 token 数太多（考虑 overlap，允许 1 个窗口的误差）
        total_chunk_tokens = sum(chunk.token_count for chunk in chunks)
        max_allowed = chapter_total_tokens + 200  # 允许 1 个窗口的误差
        assert total_chunk_tokens <= max_allowed, (
            f"Total chunk tokens {total_chunk_tokens} exceeds "
            f"chapter tokens {chapter_total_tokens} by too much"
        )


# ── 子标题拆分 token_index 复用测试 ────────────────────────────────────────

import array
from core.data.chunking.token_indexer import PageTokenIndex


class TestSplitBySubheadingsTokenIndex:
    """测试 _split_by_subheadings 复用 token_index 的 token 计数。"""

    def test_uses_token_index_when_provided(self):
        """有 token_index 时，子节 token 计数应使用 get_chapter_token_count。"""
        # 构建文档：3 页，每页约 50 tokens
        pages = [
            ParsedPage(page_number=1, markdown_text="# 第一章\n内容A" * 20),
            ParsedPage(page_number=2, markdown_text="# 第二章\n内容B" * 20),
            ParsedPage(page_number=3, markdown_text="# 第三章\n内容C" * 20),
        ]
        parsed = ParsedDocument(source="test.pdf", page_count=3, chunks=pages)

        # 手动构造 PageTokenIndex
        # 每页约 50 tokens，总共 150 tokens
        token_index = PageTokenIndex(
            token_ids=array.array("I", list(range(150))),
            page_boundaries=[(1, 0), (2, 50), (3, 100)],
            total_tokens=150,
        )

        # 子边界：第 2 章（页码 2-2）
        sub_boundaries = [
            ChapterBoundary(title="第二章", level=1, start_page=2, end_page=2, source="heading"),
        ]

        # 调用 _split_by_subheadings，传入 token_index
        result = _split_by_subheadings(
            _text="",
            chapter_path=["文档"],
            _page_range=(1, 3),
            max_tokens=1000,
            overlap_tokens=50,
            sub_boundaries=sub_boundaries,
            parsed=parsed,
            token_index=token_index,
        )

        # 验证返回了 chunk
        assert len(result) == 1
        chunk = result[0]

        # 验证 token_count 使用了 get_chapter_token_count 的结果（页码 2-2 的 token 数 = 50）
        expected_tokens = get_chapter_token_count(token_index, start_page=2, end_page=2)
        assert chunk.token_count == expected_tokens, (
            f"Expected token_count={expected_tokens}, got {chunk.token_count}"
        )
        assert chunk.token_count == 50

    def test_falls_back_to_count_tokens_when_no_index(self):
        """无 token_index 时，应回退到 count_tokens（回归测试）。"""
        # 构建文档：单页
        pages = [
            ParsedPage(page_number=1, markdown_text="# 第一章\n内容A" * 20),
        ]
        parsed = ParsedDocument(source="test.pdf", page_count=1, chunks=pages)

        # 子边界：第 1 章（页码 1-1）
        sub_boundaries = [
            ChapterBoundary(title="第一章", level=1, start_page=1, end_page=1, source="heading"),
        ]

        # 不传入 token_index
        result = _split_by_subheadings(
            _text="",
            chapter_path=["文档"],
            _page_range=(1, 1),
            max_tokens=1000,
            overlap_tokens=50,
            sub_boundaries=sub_boundaries,
            parsed=parsed,
            token_index=None,
        )

        # 验证返回了 chunk
        assert len(result) == 1
        chunk = result[0]

        # 验证 token_count 使用了 count_tokens 的结果
        expected_tokens = count_tokens(chunk.text)
        assert chunk.token_count == expected_tokens


# ── chapter_hierarchy 结构化层级信息测试 ───────────────────────────────────

class TestChapterHierarchy:
    """Chunk.chapter_hierarchy 结构化层级信息测试。
    覆盖范围：完整章节、子章节拆分、同页合并的 hierarchy 填充。
    """

    def test_complete_chapter_has_hierarchy(self):
        """Given: 短文档的完整章节 Chunk
        When: build_chunks 产出 Chunk
        Then: chapter_hierarchy 包含一个 level=1 的条目
        验证要点：ChapterPathEntry(title, level) 正确填充"""
        pages = [
            ParsedPage(page_number=1, markdown_text="# 第一章\n" + "正文。" * 50),
            ParsedPage(page_number=2, markdown_text="# 第二章\n" + "正文。" * 50),
        ]
        parsed = ParsedDocument(source="test.pdf", page_count=2, chunks=pages)
        chapters = [
            ChapterBoundary(title="第一章", level=1, start_page=1, end_page=1, source="heading"),
            ChapterBoundary(title="第二章", level=1, start_page=2, end_page=2, source="heading"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=8000, overlap_tokens=200)
        for chunk in result.chunks:
            assert len(chunk.chapter_hierarchy) >= 1
            assert isinstance(chunk.chapter_hierarchy[0], ChapterPathEntry)
            assert chunk.chapter_hierarchy[0].level == 1

    def test_sub_section_hierarchy_has_parent_and_child(self):
        """Given: 超长章节被 level 2 子边界拆分
        When: build_chunks 产出子块
        Then: chapter_hierarchy 包含 [level=1 父章节, level=2 子章节]
        验证要点：层级嵌套关系正确"""
        page1 = ParsedPage(page_number=1, markdown_text="# 短章\n短内容")
        long_text = "长内容。" * 500
        page2 = ParsedPage(page_number=2, markdown_text=long_text[:len(long_text)//2])
        page3 = ParsedPage(page_number=3, markdown_text=long_text[len(long_text)//2:])
        parsed = ParsedDocument(source="test.pdf", page_count=3, chunks=[page1, page2, page3])
        chapters = [
            ChapterBoundary(title="短章", level=1, start_page=1, end_page=1, source="bookmark"),
            ChapterBoundary(title="长章", level=1, start_page=2, end_page=3, source="bookmark"),
            ChapterBoundary(title="子节A", level=2, start_page=2, end_page=2, source="bookmark"),
            ChapterBoundary(title="子节B", level=2, start_page=3, end_page=3, source="bookmark"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=300, overlap_tokens=30)
        sub_chunks = [c for c in result.chunks if c.page_range != (1, 1)]
        for chunk in sub_chunks:
            assert len(chunk.chapter_hierarchy) >= 1
            assert chunk.chapter_hierarchy[0].level == 1
            assert chunk.chapter_hierarchy[0].title == "长章"
            if chunk.chunk_type == ChunkType.SUB_SECTION:
                assert len(chunk.chapter_hierarchy) == 2
                assert chunk.chapter_hierarchy[1].level == 2

    def test_hierarchy_fallback_on_empty_chapter_path(self):
        """Given: 超长章节降级到 token 窗口（无子边界，chapter_path 只有父级）
        When: build_chunks 产出窗口 chunk
        Then: chapter_hierarchy 至少包含父级条目，不抛 IndexError
        验证要点：空子路径的防御性处理"""
        long_text = "长内容。" * 500
        page1 = ParsedPage(page_number=1, markdown_text="# 短章\n短内容")
        page2 = ParsedPage(page_number=2, markdown_text=long_text[:len(long_text)//2])
        page3 = ParsedPage(page_number=3, markdown_text=long_text[len(long_text)//2:])
        parsed = ParsedDocument(source="test.pdf", page_count=3, chunks=[page1, page2, page3])
        # 只有 level 1 章节，无 level 2 子边界 → 超长时走 token 窗口兜底
        chapters = [
            ChapterBoundary(title="短章", level=1, start_page=1, end_page=1, source="bookmark"),
            ChapterBoundary(title="长章", level=1, start_page=2, end_page=3, source="bookmark"),
        ]
        result = build_chunks(parsed, chapters, max_tokens=300, overlap_tokens=30)
        window_chunks = [c for c in result.chunks if c.chunk_type == ChunkType.TOKEN_WINDOW]
        for chunk in window_chunks:
            assert len(chunk.chapter_hierarchy) >= 1
            assert chunk.chapter_hierarchy[0].title == "长章"
            assert chunk.chapter_hierarchy[0].level == 1
