"""Token ID 池化模块。

逐页编码 ParsedDocument，产出共享的 token ID 池 + 页码边界索引。
供 chunk_pipeline 和 chunker 全程复用，避免重复编码。
"""

from __future__ import annotations

import array
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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def get_chapter_token_count(
    index: PageTokenIndex,
    start_page: int,
    end_page: int,
) -> int:
    """计算指定页码范围内的 token 总数（含页间分隔符）。

    从 page_boundaries 直接计算，无需编码。

    Args:
        index: PageTokenIndex。
        start_page: 起始页码（1-based，含）。
        end_page: 结束页码（1-based，含）。

    Returns:
        该页码范围内的 token 数。
    """
    raise NotImplementedError
