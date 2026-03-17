"""逻辑分块引擎。

根据章节边界和 token 上限，将 ParsedDocument 切分为 ChunkList。
处理超长章节的子章节拆分和 overlap。

职责边界：
- 接收章节边界 + ParsedDocument，产出 ChunkList
- 超长章节二次拆分（按子标题 → 按 token 窗口）
- token 计数委托给 token_counter 模块
"""

from __future__ import annotations

from typing import final

from core.data.models import (
    ChapterBoundary,
    Chunk,
    ChunkList,
    ChunkMeta,
    ChunkType,
    MergedChapter,
    ParsedDocument,
)
from core.data.token_counter import (
    count_tokens,
    slice_tokens,
)
from core.data.token_indexer import (
    PageTokenIndex,
    get_chapter_token_count,
    slice_window_from_index,
)


@final
class ChunkBuilder:
    """Chunk 构建辅助类。"""

    @staticmethod
    def create_chunk(
        text: str,
        chapter_path: list[str],
        page_range: tuple[int, int],
        chunk_type: ChunkType,
        chunk_index: int = 0,
        needs_prior_summary: bool = False,
        contained_chapters: list[ChunkMeta] | None = None,
        token_count: int | None = None,
    ) -> Chunk:
        """创建 Chunk 实例。

        Args:
            text: Chunk 文本内容。
            chapter_path: 章节路径。
            page_range: 页码范围。
            chunk_type: Chunk 类型。
            chunk_index: Chunk 索引。
            needs_prior_summary: 是否需要前置摘要。
            contained_chapters: 包含的章节元数据列表。
            token_count: 可选的 token 计数。若传入则跳过内部 count_tokens 调用。
        """
        return Chunk(
            text=text,
            chapter_path=chapter_path,
            page_range=page_range,
            token_count=token_count if token_count is not None else count_tokens(text),
            chunk_type=chunk_type,
            chunk_index=chunk_index,
            needs_prior_summary=needs_prior_summary,
            contained_chapters=contained_chapters or [],
        )


def build_chunks(
    parsed: ParsedDocument,
    chapters: list[ChapterBoundary],
    max_tokens: int,
    overlap_tokens: int,
    token_index: PageTokenIndex | None = None,
) -> ChunkList:
    """根据章节边界将文档切分为 ChunkList。

    处理流程（按优先级）：
    0. **整体直通**：全文 token 数 ≤ max_tokens → 跳过章节拆分，
       整篇作为单个 COMPLETE_CHAPTER Chunk 返回
    1. **同页合并（level=1）**：对 level=1 章节列表做预处理——若相邻章节
       共享同一页面（start_page == end_page 相同），合并为一个
       虚拟章节，避免对短公告逐章节发送 LLM
    2. 对 token 数 ≤ max_tokens 的章节，直接作为完整 Chunk
    3. 对超长章节：
       a. 从完整章节边界列表中提取该章节内的 level≥2 子边界
       b. **同页合并（level=2）**：对提取的子边界做同页合并预处理
       c. 优先按合并后的子边界拆分；无预检测边界时退回正则子标题检测
       d. 仍超长的子节按 token 窗口兜底
    4. 标记每个 Chunk 的 needs_prior_summary 属性
    5. **填充 contained_chapters**：为每个 Chunk 填充 contained_chapters 列表，
       记录该 Chunk 实际包含的原始章节信息（ChunkMeta）。

    Args:
        parsed: Step 1 产出的 ParsedDocument。
        chapters: 章节边界列表。
        max_tokens: 单个 Chunk 的最大 token 数。
        overlap_tokens: 子块拆分时的 overlap token 数。
        token_index: 可选，PageTokenIndex。若传入则使用零成本 token 计数。

    Returns:
        ChunkList 对象。
    """

    # 先做同页合并
    level1_chapters = [c for c in chapters if c.level == 1]
    if not level1_chapters:
        level1_chapters = chapters
    merged_chapters = _merge_same_page_boundaries(level1_chapters)

    # Step 2 & 3: 遍历章节处理
    chunks: list[Chunk] = []
    chapter_count = len(merged_chapters)
    prev_chunk_needs_summary = False

    for i, merged in enumerate(merged_chapters):
        chapter = merged.chapter

        # 使用零成本 token 计数（如果可用）
        if token_index is not None:
            chapter_tokens = get_chapter_token_count(
                token_index, chapter.start_page, chapter.end_page
            )
            # 短章节也需要提取文本
            chapter_text = _extract_chapter_text(parsed, chapter)
        else:
            chapter_text = _extract_chapter_text(parsed, chapter)
            chapter_tokens = count_tokens(chapter_text)

        if chapter_tokens <= max_tokens:
            # 短章节：直接作为完整 Chunk
            # 使用原始章节列表来填充 contained_chapters
            contained = [
                ChunkMeta(
                    title=c.title,
                    level=c.level,
                    page_range=(c.start_page, c.end_page),
                )
                for c in merged.original_chapters
            ]
            chunk = ChunkBuilder.create_chunk(
                text=chapter_text,
                chapter_path=[chapter.title],
                page_range=(chapter.start_page, chapter.end_page),
                chunk_type=ChunkType.COMPLETE_CHAPTER,
                chunk_index=i,
                needs_prior_summary=prev_chunk_needs_summary,
                contained_chapters=contained,
                token_count=chapter_tokens,
            )
            chunks.append(chunk)
            prev_chunk_needs_summary = True  # 下一个 chunk 需要当前 chunk 的摘要
        else:
            # 超长章节：尝试二次拆分
            # a. 提取该章节内的 level>=2 子边界
            sub_boundaries = [
                c
                for c in chapters
                if c.level >= 2
                and c.start_page >= chapter.start_page
                and c.start_page <= chapter.end_page
            ]
            # b. 对子边界做同页合并
            merged_sub_boundaries = _merge_same_page_boundaries(sub_boundaries)

            # c. 优先按子边界拆分
            sub_chunks = _split_by_subheadings(
                _text=chapter_text,
                chapter_path=[chapter.title],
                _page_range=(chapter.start_page, chapter.end_page),
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                sub_boundaries=[m.chapter for m in merged_sub_boundaries]
                if merged_sub_boundaries
                else None,
                parsed=parsed,
                token_index=token_index,
            )

            if sub_chunks:
                # 使用子块拆分结果
                for j, sub_chunk in enumerate(sub_chunks):
                    chunks.append(
                        ChunkBuilder.create_chunk(
                            text=sub_chunk.text,
                            chapter_path=[chapter.title] + sub_chunk.chapter_path,
                            page_range=sub_chunk.page_range,
                            chunk_type=sub_chunk.chunk_type,  # 保留原始类型
                            chunk_index=j,
                            needs_prior_summary=prev_chunk_needs_summary,
                            contained_chapters=[
                                ChunkMeta(
                                    title=c.title,
                                    level=c.level,
                                    page_range=(c.start_page, c.end_page),
                                )
                                for c in merged.original_chapters
                            ],
                        )
                    )
                    prev_chunk_needs_summary = True
            else:
                # d. 退回 token 窗口兜底
                window_chunks = _split_by_token_window(
                    text=chapter_text,
                    chapter_path=[chapter.title],
                    page_range=(chapter.start_page, chapter.end_page),
                    max_tokens=max_tokens,
                    overlap_tokens=overlap_tokens,
                    token_index=token_index,
                )
                # 用于 contained_chapters 的原始章节列表
                original_chapters_meta = [
                    ChunkMeta(
                        title=c.title,
                        level=c.level,
                        page_range=(c.start_page, c.end_page),
                    )
                    for c in merged.original_chapters
                ]
                for j, window_chunk in enumerate(window_chunks):
                    chunks.append(
                        ChunkBuilder.create_chunk(
                            text=window_chunk.text,
                            chapter_path=[chapter.title],
                            page_range=window_chunk.page_range,
                            chunk_type=ChunkType.TOKEN_WINDOW,
                            chunk_index=j,
                            needs_prior_summary=prev_chunk_needs_summary,
                            contained_chapters=original_chapters_meta,
                        )
                    )
                    prev_chunk_needs_summary = True

    # 计算总 token 数
    total_tokens = sum(c.token_count for c in chunks)

    return ChunkList(
        source=parsed.source,
        chunks=chunks,
        total_tokens=total_tokens,
        chapter_count=chapter_count,
    )


def _merge_same_page_boundaries(
    boundaries: list[ChapterBoundary],
) -> list[MergedChapter]:
    """合并共享同一页面的相邻章节边界（通用版本）。

    当相邻边界的 start_page 和 end_page 完全相同时，
    将它们合并为一个虚拟章节。

    Args:
        boundaries: 章节边界列表（按页码升序），可以是任意 level。

    Returns:
        合并后的章节列表，每个包含合并后的边界和原始章节列表。
    """
    if not boundaries:
        return []

    result: list[MergedChapter] = []
    current_originals: list[ChapterBoundary] = [boundaries[0]]

    for next_boundary in boundaries[1:]:
        # 检查是否共享同一页面
        current = current_originals[0]
        if (
            current.start_page
            == current.end_page
            == next_boundary.start_page
            == next_boundary.end_page
        ):
            current_originals.append(next_boundary)
            continue

        # 不合并，保存当前并开始新的
        merged_chapter = ChapterBoundary(
            title=" / ".join(c.title for c in current_originals),
            level=min(c.level for c in current_originals),
            start_page=current_originals[0].start_page,
            end_page=current_originals[0].end_page,
            source=current_originals[0].source,
        )
        result.append(
            MergedChapter(chapter=merged_chapter, original_chapters=current_originals)
        )
        current_originals = [next_boundary]

    # 保存最后一个
    if current_originals:
        current = current_originals[0]
        merged_chapter = ChapterBoundary(
            title=" / ".join(c.title for c in current_originals),
            level=min(c.level for c in current_originals),
            start_page=current.start_page,
            end_page=current.start_page,
            source=current_originals[0].source,
        )
        result.append(
            MergedChapter(chapter=merged_chapter, original_chapters=current_originals)
        )

    return result


def _extract_chapter_text(
    parsed: ParsedDocument,
    chapter: ChapterBoundary,
) -> str:
    """从 ParsedDocument 中提取指定章节的 Markdown 文本。

    将章节页码范围内的所有页面文本拼接。

    Args:
        parsed: Step 1 产出的 ParsedDocument。
        chapter: 章节边界。

    Returns:
        拼接后的 Markdown 文本。
    """
    texts: list[str] = []
    for page_idx in range(chapter.start_page - 1, chapter.end_page):
        if page_idx < len(parsed.chunks):
            texts.append(parsed.chunks[page_idx].markdown_text)
    return "\n\n".join(texts)


def _split_by_subheadings(
    _text: str,
    chapter_path: list[str],
    _page_range: tuple[int, int],
    *,
    max_tokens: int,
    overlap_tokens: int,
    sub_boundaries: list[ChapterBoundary] | None = None,
    parsed: ParsedDocument | None = None,
    token_index: PageTokenIndex | None = None,
) -> list[Chunk]:
    """尝试按子标题拆分超长章节。

    拆分边界来源：
    1. **预检测边界**：若 sub_boundaries 非空，使用章节检测器提供的
       level≥2 子边界按页码范围切分文本
    2. **无预检测边界**：直接返回空列表，触发调用方降级到 token 窗口

    Args:
        _text: 章节 Markdown 文本（保留参数，仅在有预检测边界时使用）。
        chapter_path: 当前章节路径。
        _page_range: 章节页码范围（保留参数，仅在有预检测边界时使用）。
        max_tokens: 单块最大 token 数。
        overlap_tokens: overlap token 数。
        sub_boundaries: 可选，章节检测器提供的 level≥2 子章节边界。
        parsed: 可选，ParsedDocument，用于从原始页面数据提取子边界文本。

    Returns:
        Chunk 列表，或空列表表示无法按子标题拆分。
    """
    if sub_boundaries and parsed:
        # 使用预检测边界拆分（按页码范围）
        # 从 parsed 原始页面数据提取文本，而非使用 text.split("\n\n") 后用页码索引
        boundary_chunks: list[Chunk] = []

        for boundary in sub_boundaries:
            # 从 ParsedDocument 按页码范围提取文本
            sub_text = _extract_chapter_text(parsed, boundary)
            if not sub_text:
                continue

            # 优先使用 token_index 预计算的 token 计数，避免即时编码
            if token_index is not None:
                sub_tokens = get_chapter_token_count(
                    token_index, boundary.start_page, boundary.end_page
                )
            else:
                sub_tokens = count_tokens(sub_text)

            if sub_tokens <= max_tokens:
                boundary_chunks.append(
                    ChunkBuilder.create_chunk(
                        text=sub_text,
                        chapter_path=chapter_path + [boundary.title],
                        page_range=(boundary.start_page, boundary.end_page),
                        chunk_type=ChunkType.SUB_SECTION,
                        chunk_index=len(boundary_chunks),
                        needs_prior_summary=len(boundary_chunks) > 0,
                        token_count=sub_tokens,
                    )
                )
            else:
                # 超长子节：直接降级到 token 窗口兜底
                window_chunks = _split_by_token_window(
                    text=sub_text,
                    chapter_path=chapter_path + [boundary.title],
                    page_range=(boundary.start_page, boundary.end_page),
                    max_tokens=max_tokens,
                    overlap_tokens=overlap_tokens,
                    token_index=token_index,
                )
                for j, wc in enumerate(window_chunks):
                    boundary_chunks.append(
                        ChunkBuilder.create_chunk(
                            text=wc.text,
                            chapter_path=chapter_path + [boundary.title],
                            page_range=wc.page_range,
                            chunk_type=ChunkType.TOKEN_WINDOW,
                            chunk_index=j,
                            needs_prior_summary=len(boundary_chunks) > 0,
                        )
                    )

        if boundary_chunks:
            return boundary_chunks

    # 无预检测边界：直接返回空列表，触发调用方降级到 token 窗口
    return []


def _split_by_token_window(
    text: str,
    chapter_path: list[str],
    page_range: tuple[int, int],
    *,
    max_tokens: int,
    overlap_tokens: int,
    token_index: PageTokenIndex | None = None,
) -> list[Chunk]:
    """按 token 窗口 + overlap 切分文本。

    如果传入 token_index，使用 slice_window_from_index 从 token ID 池切窗口；
    否则使用简单的滑动窗口逻辑。

    Args:
        text: 待切分的 Markdown 文本。
        chapter_path: 章节路径。
        page_range: 页码范围。
        max_tokens: 单块最大 token 数。
        overlap_tokens: overlap token 数。
        token_index: 可选，PageTokenIndex。若传入则使用零成本 token 切分。

    Returns:
        Chunk 列表（至少一个元素）。
    """
    if token_index is not None:
        return _split_by_token_window_with_index(
            text=text,
            chapter_path=chapter_path,
            page_range=page_range,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            token_index=token_index,
        )

    # 降级逻辑：使用简单的滑动窗口
    total = count_tokens(text)
    if total <= max_tokens:
        # 文本可以直接放下
        return [
            ChunkBuilder.create_chunk(
                text=text,
                chapter_path=chapter_path,
                page_range=page_range,
                chunk_type=ChunkType.TOKEN_WINDOW,
                chunk_index=0,
                needs_prior_summary=False,
            )
        ]

    # 滑动窗口拆分
    chunks: list[Chunk] = []
    step = max_tokens - overlap_tokens
    start = 0
    chunk_idx = 0

    while start < total:
        end = min(start + max_tokens, total)
        window_text = slice_tokens(text, start, end - start)

        if window_text:
            chunks.append(
                ChunkBuilder.create_chunk(
                    text=window_text,
                    chapter_path=chapter_path,
                    page_range=page_range,
                    chunk_type=ChunkType.TOKEN_WINDOW,
                    chunk_index=chunk_idx,
                    needs_prior_summary=chunk_idx > 0,
                )
            )
            chunk_idx += 1

        start += step

    # 确保至少返回一个 chunk
    if not chunks:
        chunks.append(
            ChunkBuilder.create_chunk(
                text=text[:1000] if text else "",
                chapter_path=chapter_path,
                page_range=page_range,
                chunk_type=ChunkType.TOKEN_WINDOW,
                chunk_index=0,
                needs_prior_summary=False,
            )
        )

    return chunks


def _split_by_token_window_with_index(
    text: str,
    chapter_path: list[str],
    page_range: tuple[int, int],
    *,
    max_tokens: int,
    overlap_tokens: int,
    token_index: PageTokenIndex,
) -> list[Chunk]:
    """使用 token ID 池切分文本。

    从 token_index 中按页码范围（page_range）切取窗口，每个窗口使用
    slice_window_from_index 获取文本和页码范围。

    注意：本函数只在本章节 token 范围内切分，不跨越章节边界。

    Args:
        text: 待切分的 Markdown 文本（用于降级 fallback）。
        chapter_path: 章节路径。
        page_range: 页码范围（章节在文档中的起始和结束页码）。
        max_tokens: 单块最大 token 数。
        overlap_tokens: overlap token 数。
        token_index: PageTokenIndex。

    Returns:
        Chunk 列表（至少一个元素）。
    """
    # 1. 定位章节在 token 池中的起止位置
    chapter_start_token: int | None = None
    end_idx: int | None = None

    for i, (page_num, token_start) in enumerate(token_index.page_boundaries):
        if page_num == page_range[0]:
            chapter_start_token = token_start
        if page_num == page_range[1]:
            end_idx = i
            break

    # 如果无法定位章节范围，降级到无 index 的简单滑动窗口
    if chapter_start_token is None or end_idx is None:
        return _split_by_token_window_fallback(
            text=text,
            chapter_path=chapter_path,
            page_range=page_range,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    # 计算章节总 token 数（不排除分隔符，因为分隔符也是实际内容）
    # 使用 page_boundaries 的差值来计算
    chapter_end_idx = end_idx + 1
    if chapter_end_idx < len(token_index.page_boundaries):
        # 章节结束 token = 下一页的起始 token
        chapter_end_token = token_index.page_boundaries[chapter_end_idx][1]
    else:
        # 最后一章，到文档末尾
        chapter_end_token = token_index.total_tokens

    # 2. 在章节 token 范围内滑动窗口
    chunks: list[Chunk] = []
    start = chapter_start_token

    while start < chapter_end_token:
        # 计算本窗口的实际长度（不超过章节结束位置）
        remaining_in_chapter = chapter_end_token - start

        # 修复：如果剩余 tokens 不足 overlap，不足以形成有效窗口，结束循环
        # 必须先检查再添加 chunk，避免多添加一个窗口
        if remaining_in_chapter <= overlap_tokens:
            break

        # 如果剩余 tokens 不足一个完整窗口，直接把剩余部分作为一个窗口
        # 不再应用 overlap，确保覆盖所有剩余 tokens
        if remaining_in_chapter <= max_tokens:
            window_length = remaining_in_chapter
        else:
            window_length = max_tokens

        # 切取窗口
        window_text, actual_tokens, window_page_range = slice_window_from_index(
            index=token_index,
            start=start,
            length=window_length,
        )

        # 修复：检查实际切取的 tokens 是否会导致超出章节范围
        # slice_window_from_index 可能返回超出 chapter_end_token 的 tokens
        if start + actual_tokens > chapter_end_token:
            # 调整 actual_tokens 不超过剩余范围
            actual_tokens = remaining_in_chapter
            # 重新切取正确范围的文本
            if actual_tokens > 0:
                window_text, actual_tokens, window_page_range = slice_window_from_index(
                    index=token_index,
                    start=start,
                    length=actual_tokens,
                )

        # 如果窗口文本为空，降级到截断处理
        if not window_text:
            # 降级：截取剩余文本
            # 将全局 token 索引转换为章节内偏移
            chapter_offset = start - chapter_start_token
            remaining_text = slice_tokens(text, chapter_offset, max_tokens)
            if remaining_text:
                chunks.append(
                    ChunkBuilder.create_chunk(
                        text=remaining_text,
                        chapter_path=chapter_path,
                        page_range=page_range,
                        chunk_type=ChunkType.TOKEN_WINDOW,
                        chunk_index=len(chunks),
                        needs_prior_summary=len(chunks) > 0,
                    )
                )
            break

        # 构建 Chunk（使用实际的 token 计数）
        chunks.append(
            ChunkBuilder.create_chunk(
                text=window_text,
                chapter_path=chapter_path,
                page_range=window_page_range,
                chunk_type=ChunkType.TOKEN_WINDOW,
                chunk_index=len(chunks),
                needs_prior_summary=len(chunks) > 0,
                token_count=actual_tokens,
            )
        )

        # 移动窗口（考虑 overlap）
        # 注意：使用实际切取的 token 数 actual_tokens，而非固定的 max_tokens
        # 因为接近章节末尾时，实际切取的 token 数可能小于 max_tokens
        start += actual_tokens - overlap_tokens

    # 确保至少返回一个 chunk
    if not chunks:
        chunks.append(
            ChunkBuilder.create_chunk(
                text=text[:1000] if text else "",  # 降级：截取前 1000 字符
                chapter_path=chapter_path,
                page_range=page_range,
                chunk_type=ChunkType.TOKEN_WINDOW,
                chunk_index=0,
                needs_prior_summary=False,
            )
        )

    return chunks


def _split_by_token_window_fallback(
    text: str,
    chapter_path: list[str],
    page_range: tuple[int, int],
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """无 token_index 时的降级滑动窗口实现。

    Args:
        text: 待切分的 Markdown 文本。
        chapter_path: 章节路径。
        page_range: 页码范围。
        max_tokens: 单块最大 token 数。
        overlap_tokens: overlap token 数。

    Returns:
        Chunk 列表（至少一个元素）。
    """
    total = count_tokens(text)
    if total <= max_tokens:
        return [
            ChunkBuilder.create_chunk(
                text=text,
                chapter_path=chapter_path,
                page_range=page_range,
                chunk_type=ChunkType.TOKEN_WINDOW,
                chunk_index=0,
                needs_prior_summary=False,
            )
        ]

    chunks: list[Chunk] = []
    step = max_tokens - overlap_tokens
    start = 0
    chunk_idx = 0

    while start < total:
        end = min(start + max_tokens, total)
        window_text = slice_tokens(text, start, end - start)

        if window_text:
            chunks.append(
                ChunkBuilder.create_chunk(
                    text=window_text,
                    chapter_path=chapter_path,
                    page_range=page_range,
                    chunk_type=ChunkType.TOKEN_WINDOW,
                    chunk_index=chunk_idx,
                    needs_prior_summary=chunk_idx > 0,
                )
            )
            chunk_idx += 1

        start += step

    # 确保至少返回一个 chunk
    if not chunks:
        chunks.append(
            ChunkBuilder.create_chunk(
                text=text[:1000] if text else "",
                chapter_path=chapter_path,
                page_range=page_range,
                chunk_type=ChunkType.TOKEN_WINDOW,
                chunk_index=0,
                needs_prior_summary=False,
            )
        )

    return chunks
