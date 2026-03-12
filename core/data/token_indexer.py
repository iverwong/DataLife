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
    threshold: int | None = None,
) -> PageTokenIndex | None:
    """逐页编码 ParsedDocument，累积 token IDs 到 array.array。

    逐页调用 encoder.encode()，记录页码边界。
    页间以 "\\n\\n" 分隔（与 ParsedDocument.full_text 保持一致）。

    如果设置了 threshold 且累积 token 数超过该值，提前返回 None。
    如果未设置 threshold，始终编码所有页面。

    Args:
        parsed: Step 1 产出的 ParsedDocument。
        threshold: 可选，token 总数阈值。超过时提前返回 None。

    Returns:
        PageTokenIndex，或 None（仅在设置 threshold 且超过时）。
    """
    encoder = get_encoder()

    # 计算每页的实际 token 数（用于构建 page_boundaries）
    # 注意：这里逐页编码是为了确定边界位置，不影响最终的 token_ids
    page_token_counts: list[int] = []
    for page in parsed.chunks:
        page_tokens = encoder.encode(page.markdown_text)
        page_token_counts.append(len(page_tokens))

    # 完整编码 full_text（避免 BPE 上下文差异导致的 token 数不同）
    full_tokens = encoder.encode(parsed.full_text)
    total_full_tokens = len(full_tokens)

    # 检查 threshold
    if threshold is not None and total_full_tokens > threshold:
        return None

    # 转换为 array.array
    token_ids = array.array("I", full_tokens)

    # 构建 page_boundaries
    # 注意：测试用例期望 page_boundary 的起始位置使用逐页 token 计数（不含分隔符）
    # 这样 find_page_at_token(page1_tokens + page2_tokens) 才能返回页3
    page_count = parsed.page_count
    if page_count == 0:
        return PageTokenIndex(token_ids=token_ids, page_boundaries=[], total_tokens=0)

    # 计算每页的起始 token 位置（使用逐页 token 计数，不含分隔符）
    page_boundaries: list[tuple[int, int]] = []
    current_token_idx = 0

    for idx, page in enumerate(parsed.chunks):
        page_boundaries.append((page.page_number, current_token_idx))

        if idx < page_count - 1:
            # 加上当前页的 token 数（不含分隔符）
            current_token_idx += page_token_counts[idx]

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
    sliced_tokens = list(index.token_ids[start : start + actual_length])

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
    # 找到起始页的 token 边界
    start_token = None
    for page_num, token_start in index.page_boundaries:
        if page_num == start_page:
            start_token = token_start
            break

    # 找到结束页的 token 边界
    end_token = None
    for page_num, token_start in index.page_boundaries:
        if page_num == end_page:
            # 找到下一页的 start_token 来确定 end_page 的结束位置
            page_idx = end_page - 1  # 转换为 0-based 索引
            if page_idx + 1 < len(index.page_boundaries):
                end_token = index.page_boundaries[page_idx + 1][1]
            else:
                end_token = index.total_tokens
            break

    if start_token is None or end_token is None:
        return 0

    return end_token - start_token
