"""Token ID 池化模块。

逐页编码 ParsedDocument，产出共享的 token ID 池 + 页码边界索引。
供 chunk_pipeline 和 chunker 全程复用，避免重复编码。
"""

from __future__ import annotations

import array
import bisect
from dataclasses import dataclass

from core.data.models import ParsedDocument
from core.data.token_counter import get_encoder


@dataclass(frozen=True)
class PageTokenIndex:
    """逐页编码结果，作为 pipeline 内部共享的 token ID 池。

    Attributes:
        token_ids: 全文档的 token ID 扁平数组（unsigned int, 4 bytes/token）。
        page_boundaries: 每页的 (page_number, token_start_index)，按页码升序。
        total_tokens: token 总数，等于 len(token_ids)。
    """

    token_ids: array.array[int]  # array('I')
    page_boundaries: list[tuple[int, int]]
    total_tokens: int


def encode_pages_incremental(
    parsed: ParsedDocument,
) -> PageTokenIndex:
    """逐页编码 ParsedDocument，累积 token IDs 到 array.array。

    逐页调用 encoder.encode()，记录页码边界。
    页间以 "\\n\\n" 分隔（与 ParsedDocument.full_text 保持一致）。

    Args:
        parsed: Step 1 产出的 ParsedDocument。

    Returns:
        PageTokenIndex。
    """
    encoder = get_encoder()

    # 扁平 token ID 池，使用 unsigned int（4 bytes/token）节省内存
    token_ids = array.array("I")

    # 页码边界：记录每页第一个 token 在 token_ids 中的起始索引
    page_boundaries: list[tuple[int, int]] = []

    # 预编码页间分隔符，避免循环内重复编码
    # 与 ParsedDocument.full_text 的 "\n\n".join() 行为保持一致
    separator_ids = encoder.encode("\n\n")

    for idx, page in enumerate(parsed.chunks):
        # 记录当前页的起始位置（此时 len(token_ids) 即为该页第一个 token 的索引）
        page_boundaries.append((page.page_number, len(token_ids)))

        # 逐页编码并追加到池中（每页只编码一次）
        token_ids.extend(encoder.encode(page.markdown_text))

        # 非最后一页时追加分隔符 token
        if idx < parsed.page_count - 1:
            token_ids.extend(separator_ids)

    return PageTokenIndex(
        token_ids=token_ids,
        page_boundaries=page_boundaries,
        total_tokens=len(token_ids),
    )


def find_page_at_token(
    page_boundaries: list[tuple[int, int]],
    token_idx: int,
) -> int:
    """二分查找 token_idx 所在的页码（1-based）。

    Args:
        page_boundaries: encode_pages_incremental 产出的页码边界列表。
        token_idx: token 索引（0-based）。

    Returns:
        该 token 所在的页码（1-based）。
    """
    # 提取所有页的起始 token 索引
    token_starts = [boundary[1] for boundary in page_boundaries]

    # bisect_right 找到 token_idx 所在的页面索引
    # bisect_right 返回第一个 > token_idx 的位置，所以减 1 得到包含 token_idx 的页
    page_idx = bisect.bisect_right(token_starts, token_idx) - 1

    # 确保页码在有效范围内
    if page_idx < 0:
        page_idx = 0

    return page_boundaries[page_idx][0]


def slice_window_from_index(
    index: PageTokenIndex,
    start: int,
    length: int,
) -> tuple[str, int, tuple[int, int]]:
    """从 token ID 池中切取窗口，decode 为文本，并计算页码范围。

    Args:
        index: encode_pages_incremental 产出的 PageTokenIndex。
        start: 窗口起始 token 索引（0-based）。
        length: 窗口 token 数量。

    Returns:
        (text, actual_token_count, (page_start, page_end)) 三元组。
        actual_token_count 可能小于 length（当窗口超出文档末尾时）。
    """
    encoder = get_encoder()

    # 边界处理：确保 start 不超出范围
    if start >= index.total_tokens:
        return "", 0, (0, 0)

    # 计算实际能切取的 token 数量
    actual_length = min(length, index.total_tokens - start)

    # 切片 token IDs
    sliced_tokens = index.token_ids[start : start + actual_length]

    # 解码为文本
    text = encoder.decode(sliced_tokens)

    # 计算页码范围
    page_start = find_page_at_token(index.page_boundaries, start)
    end_idx = start + actual_length - 1
    page_end = find_page_at_token(index.page_boundaries, end_idx)

    return text, actual_length, (page_start, page_end)


def get_chapter_token_count(
    index: PageTokenIndex,
    start_page: int,
    end_page: int,
) -> int:
    """计算指定页码范围内的 token 总数（含页间分隔符）。

    从 page_boundaries 直接计算，无需编码。
    使用 end_page 的下一页 start_token 减去 start_page 的 start_token 来计算。

    Args:
        index: PageTokenIndex。
        start_page: 起始页码（1-based，含）。
        end_page: 结束页码（1-based，含）。

    Returns:
        该页码范围内的 token 数。
    """
    # 找到起始页的 token 边界（线性查找，不依赖页码连续性）
    start_token = None
    end_token = None

    for i, (page_num, token_start) in enumerate(index.page_boundaries):
        if page_num == start_page and start_token is None:
            start_token = token_start
        if page_num == end_page:
            # 用实际遍历位置 i 找下一页，而非 end_page - 1
            if i + 1 < len(index.page_boundaries):
                end_token = index.page_boundaries[i + 1][1]
            else:
                end_token = index.total_tokens
            break

    if start_token is None or end_token is None:
        return 0

    return end_token - start_token
