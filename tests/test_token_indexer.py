"""Token Indexer 模块测试。

验证 token ID 池化、页码边界索引功能的契约正确性。
"""

from __future__ import annotations

import array

from core.data.models import PageChunk, PDFParseResult
from core.data.token_counter import count_tokens, get_encoder
from core.data.token_indexer import (
    PageTokenIndex,
    encode_pages_incremental,
    find_page_at_token,
    get_chapter_token_count,
    slice_window_from_index,
)


class TestEncodePagesIncremental:
    """encode_pages_incremental 函数测试。"""

    def test_single_page_document(self):
        """单页文档，验证 token_ids 长度 = count_tokens 结果。"""
        # 构建单页 ParsedDocument
        page_text = "这是一段测试文本。" * 50
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=1,
            chunks=[
                PageChunk(
                    page_number=1,
                    markdown_text=page_text,
                    metadata={},
                    toc_items=[],
                    page_boxes=[],
                ),
            ],
        )

        # 执行编码
        result = encode_pages_incremental(parsed)

        # 验证结果非空
        assert result is not None
        # 验证 token_ids 长度等于 count_tokens(full_text) 结果
        expected_tokens = count_tokens(parsed.full_text)
        assert len(result.token_ids) == expected_tokens

    def test_multi_page_boundaries(self):
        """多页文档，验证 page_boundaries 记录正确。"""
        # 构建 3 页文档
        pages = [
            PageChunk(
                page_number=1,
                markdown_text="第一页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text="第二页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=3,
                markdown_text="第三页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=3,
            chunks=pages,
        )

        result = encode_pages_incremental(parsed)

        assert result is not None
        # page_boundaries 应有 3 条记录（每页一个）
        assert len(result.page_boundaries) == 3
        # 验证每条记录格式 (page_number, token_start_index)
        assert result.page_boundaries[0][0] == 1
        assert result.page_boundaries[1][0] == 2
        assert result.page_boundaries[2][0] == 3
        # 验证起始索引递增
        assert result.page_boundaries[0][1] == 0
        assert result.page_boundaries[1][1] > result.page_boundaries[0][1]
        assert result.page_boundaries[2][1] > result.page_boundaries[1][1]

    def test_always_completes_for_large_documents(self):
        """不设阈值，大文档也完成编码。"""
        # 构建大文档（约 5000+ tokens）
        large_text = "这是测试内容。" * 500
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=1,
            chunks=[
                PageChunk(
                    page_number=1,
                    markdown_text=large_text,
                    metadata={},
                    toc_items=[],
                    page_boxes=[],
                ),
            ],
        )

        # 不设置阈值
        result = encode_pages_incremental(parsed)

        # 验证完成编码
        assert result is not None
        expected_tokens = count_tokens(parsed.full_text)
        assert len(result.token_ids) == expected_tokens

    def test_bpe_consistency(self):
        """逐页 encode + extend vs 全文 encode，token 数一致。"""
        decoder = get_encoder()
        # 构建多页文档
        pages = [
            PageChunk(
                page_number=1,
                markdown_text="第一页的测试内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text="第二页的测试内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=3,
                markdown_text="第三页的测试内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=3,
            chunks=pages,
        )

        result = encode_pages_incremental(parsed)

        assert result is not None
        # 逐页编码的总 token 数应大于等于全文编码的 token 数
        expected_total = count_tokens(parsed.full_text)
        assert result.total_tokens >= expected_total
        # decode一致性
        assert decoder.decode(result.token_ids) == parsed.full_text


class TestFindPageAtToken:
    """find_page_at_token 函数测试。"""

    def test_find_page_at_token(self):
        """各种位置的页码查找。"""
        # 构建 3 页文档，每页 token 数不同
        # 先获取各页 token 数以便计算边界
        page1_text = "第一页"
        page2_text = "第二页内容较多" * 10
        page3_text = "第三页内容更多更多" * 20

        pages = [
            PageChunk(
                page_number=1,
                markdown_text=page1_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text=page2_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=3,
                markdown_text=page3_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=3,
            chunks=pages,
        )

        index = encode_pages_incremental(parsed)
        assert index is not None

        # 测试第一页的 token（索引 0）
        assert find_page_at_token(index.page_boundaries, 0) == 1

        # 测试中间页的 token（需要计算）
        assert (
            find_page_at_token(index.page_boundaries, index.page_boundaries[1][1]) == 2
        )

        # 测试最后一页的 token
        assert (
            find_page_at_token(index.page_boundaries, index.page_boundaries[2][1]) == 3
        )

    def test_find_page_at_token_boundary(self):
        """恰好在页面边界的 token。"""
        # 构建 2 页文档
        page1_text = "AAA" * 50  # 约 150 tokens
        page2_text = "BBB" * 50

        pages = [
            PageChunk(
                page_number=1,
                markdown_text=page1_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text=page2_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=2,
            chunks=pages,
        )

        index = encode_pages_incremental(parsed)
        assert index is not None

        # 获取第一页结束时的 token 索引
        page1_token_count = count_tokens(page1_text)
        # 加上页间分隔符 "\n\n" 的 token
        separator_tokens = count_tokens("\n\n")

        # 边界 token（第一页最后一个 token）
        boundary_idx = page1_token_count - 1
        assert find_page_at_token(index.page_boundaries, boundary_idx) == 1

        # 边界 token（第二页第一个 token，即 page1_tokens + separator_tokens）
        boundary_idx2 = page1_token_count + separator_tokens
        assert find_page_at_token(index.page_boundaries, boundary_idx2) == 2


class TestSliceWindowFromIndex:
    """slice_window_from_index 函数测试。"""

    def test_slice_window_from_index(self):
        """切窗口文本 + 页码范围正确。"""
        pages = [
            PageChunk(
                page_number=1,
                markdown_text="第一页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text="第二页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=2,
            chunks=pages,
        )

        index = encode_pages_incremental(parsed)
        assert index is not None

        # 从 token 0 开始，切取 10 个 token
        text, actual_count, page_range = slice_window_from_index(index, 0, 10)

        # 验证返回文本非空
        assert isinstance(text, str)
        assert len(text) > 0
        # 验证 actual_token_count 大于 0
        assert actual_count > 0
        # 验证页码范围
        assert page_range[0] == 1
        assert page_range[1] >= page_range[0]

    def test_slice_window_cross_page(self):
        """窗口跨页时页码范围精确。"""
        # 构建两页，确保窗口会跨页
        page1_text = "第一页" * 50  # 约 100 tokens
        page2_text = "第二页" * 50

        pages = [
            PageChunk(
                page_number=1,
                markdown_text=page1_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text=page2_text,
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=2,
            chunks=pages,
        )

        index = encode_pages_incremental(parsed)
        assert index is not None

        # 从接近第一页末尾的位置开始切窗口，确保跨页
        page1_token_count = count_tokens(page1_text)
        start = page1_token_count - 10  # 第一页末尾附近
        length = 30

        _text, _actual_count, page_range = slice_window_from_index(index, start, length)

        # 验证页码范围包含两页
        assert page_range[0] == 1
        assert page_range[1] == 2


class TestGetChapterTokenCount:
    """get_chapter_token_count 函数测试。"""

    def test_get_chapter_token_count(self):
        """章节 token 计数 vs 编码验证。"""
        pages = [
            PageChunk(
                page_number=1,
                markdown_text="第一页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=2,
                markdown_text="第二页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
            PageChunk(
                page_number=3,
                markdown_text="第三页内容。",
                metadata={},
                toc_items=[],
                page_boxes=[],
            ),
        ]
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=3,
            chunks=pages,
        )

        index = encode_pages_incremental(parsed)
        assert index is not None

        boundaries = index.page_boundaries
        _, s1 = boundaries[0]  # page1 起始
        _, s2 = boundaries[1]  # page2 起始
        _, s3 = boundaries[2]  # page3 起始

        # 第 1-2 页的 token 数 = page3 起始位置 - page1 起始位置
        chapter_tokens = get_chapter_token_count(index, start_page=1, end_page=2)
        assert chapter_tokens == s3 - s1
        assert chapter_tokens > 0

        # 单页：第 1 页的 token 数 = page2 起始 - page1 起始
        single_page = get_chapter_token_count(index, start_page=1, end_page=1)
        assert single_page == s2 - s1

        # 全部页：第 1-3 页 = 总 token 数 - page1 起始
        all_pages = get_chapter_token_count(index, start_page=1, end_page=3)
        assert all_pages == index.total_tokens - s1

    def test_consecutive_pages(self):
        """页码连续时的回归测试（page_boundaries = [(1, 0), (2, 100), (3, 200)]）。"""
        # 手动构造 PageTokenIndex，模拟连续页码
        index = PageTokenIndex(
            token_ids=array.array("I", list(range(300))),
            page_boundaries=[(1, 0), (2, 100), (3, 200)],
            total_tokens=300,
        )

        # 查询第 2 页（start_page=2, end_page=2）
        result = get_chapter_token_count(index, start_page=2, end_page=2)
        # 预期：第2页的token数 = 200 - 100 = 100
        assert result == 100

    def test_non_consecutive_pages(self):
        """页码不连续时的防御性验证（page_boundaries = [(1, 0), (3, 100), (6, 200)]）。"""
        # 手动构造 PageTokenIndex，模拟不连续页码（跳过第2、4、5页）
        index = PageTokenIndex(
            token_ids=array.array("I", list(range(300))),
            page_boundaries=[(1, 0), (3, 100), (6, 200)],
            total_tokens=300,
        )

        # 查询第 3 页（start_page=3, end_page=3）
        # 第3页在数组中的位置是 index=1（第2个元素），不是 page_num-1=2
        result = get_chapter_token_count(index, start_page=3, end_page=3)
        # 预期：第3页的token数 = 200 - 100 = 100
        assert result == 100

    def test_last_page(self):
        """最后一页应使用 total_tokens 作为结束位置。"""
        # 手动构造 PageTokenIndex
        index = PageTokenIndex(
            token_ids=array.array("I", list(range(300))),
            page_boundaries=[(1, 0), (2, 100), (5, 200)],
            total_tokens=300,
        )

        # 查询第 5 页（最后一页）
        result = get_chapter_token_count(index, start_page=5, end_page=5)
        # 预期：第5页的token数 = total_tokens(300) - 200 = 100
        assert result == 100


class TestArrayMemoryType:
    """验证 token_ids 使用 array.array 而非 list。"""

    def test_array_memory_type(self):
        """验证 token_ids 是 array.array 而非 list。"""
        page_text = "测试文本。" * 50
        parsed = PDFParseResult(
            source="test.pdf",
            page_count=1,
            chunks=[
                PageChunk(
                    page_number=1,
                    markdown_text=page_text,
                    metadata={},
                    toc_items=[],
                    page_boxes=[],
                ),
            ],
        )

        result = encode_pages_incremental(parsed)

        assert result is not None
        # 验证 token_ids 是 array.array 类型
        assert isinstance(result.token_ids, array.array)
        # 验证不是 list
        assert not isinstance(result.token_ids, list)
