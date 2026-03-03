"""逻辑分块引擎。

根据章节边界和 token 上限，将 ParsedDocument 切分为 ChunkList。
处理超长章节的子章节拆分和 overlap。

职责边界：
- 接收章节边界 + ParsedDocument，产出 ChunkList
- 超长章节二次拆分（按子标题 → 按 token 窗口）
- token 计数委托给 token_counter 模块
"""

from __future__ import annotations

import re
from typing import final

from core.data.models import (
    ChapterBoundary,
    Chunk,
    ChunkList,
    ChunkMeta,
    ChunkType,
    ParsedDocument,
)
from core.data.token_counter import count_tokens, truncate_to_tokens

# ── 常量 ──────────────────────────────────────────────────────────────
DEFAULT_MAX_TOKENS: int = 8000
"""单个 Chunk 的最大 token 数（DeepSeek 有效摘要窗口）。
可通过 chunk_document(max_tokens=...) 或 build_chunks(max_tokens=...) 参数覆盖。
建议根据实际 DeepSeek 摘要质量测试结果调整此默认值。"""

OVERLAP_TOKENS: int = 200
"""子块拆分时的 overlap token 数。"""


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
    ) -> Chunk:
        """创建 Chunk 实例。"""
        return Chunk(
            text=text,
            chapter_path=chapter_path,
            page_range=page_range,
            token_count=count_tokens(text),
            chunk_type=chunk_type,
            chunk_index=chunk_index,
            needs_prior_summary=needs_prior_summary,
            contained_chapters=contained_chapters or [],
        )


def build_chunks(
    parsed: ParsedDocument,
    chapters: list[ChapterBoundary],
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
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

    Returns:
        ChunkList 对象。
    """
    # Step 0: 整体直通检查（同页合并后只有1个章节 且 全文 <= max_tokens）
    full_text = parsed.full_text

    # 先做同页合并
    level1_chapters = [c for c in chapters if c.level == 1]
    if not level1_chapters:
        level1_chapters = chapters
    merged_chapters = _merge_same_page_boundaries(level1_chapters)

    # 只有当同页合并后只有1个章节 且 全文 <= max_tokens 时才整体直通
    if len(merged_chapters) == 1 and count_tokens(full_text) <= max_tokens:
        contained = [
            ChunkMeta(
                title=c.title,
                level=c.level,
                page_range=(c.start_page, c.end_page),
            )
            for c in level1_chapters
        ]
        chunk = ChunkBuilder.create_chunk(
            text=full_text,
            chapter_path=[],
            page_range=(1, parsed.page_count),
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            chunk_index=0,
            needs_prior_summary=False,
            contained_chapters=contained,
        )
        return ChunkList(
            source=parsed.source,
            chunks=[chunk],
            total_tokens=chunk.token_count,
            chapter_count=len(level1_chapters) or 1,
        )

    # Step 2 & 3: 遍历章节处理
    chunks: list[Chunk] = []
    chapter_count = len(merged_chapters)
    prev_chunk_needs_summary = False

    for i, merged in enumerate(merged_chapters):
        chapter = merged.chapter
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
                text=chapter_text,
                chapter_path=[chapter.title],
                page_range=(chapter.start_page, chapter.end_page),
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                sub_boundaries=[m.chapter for m in merged_sub_boundaries]
                if merged_sub_boundaries
                else None,
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


from dataclasses import dataclass


@dataclass
class MergedChapter:
    """合并后的章节信息，包含原始章节列表。"""

    chapter: ChapterBoundary
    original_chapters: list[ChapterBoundary]


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

    # 按 start_page 排序
    sorted_boundaries = sorted(boundaries, key=lambda b: b.start_page)

    result: list[MergedChapter] = []
    current_originals: list[ChapterBoundary] = [sorted_boundaries[0]]

    for next_boundary in sorted_boundaries[1:]:
        # 检查是否共享同一页面
        current = current_originals[0]
        if (
            current.start_page == current.end_page
            and next_boundary.start_page == next_boundary.end_page
        ):
            if current.start_page == next_boundary.start_page:
                # 合并
                current_originals.append(next_boundary)
                continue

        # 不合并，保存当前并开始新的
        merged_chapter = ChapterBoundary(
            title=" / ".join(c.title for c in current_originals),
            level=min(c.level for c in current_originals),
            start_page=current_originals[0].start_page,
            end_page=max(c.end_page for c in current_originals),
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
            start_page=current_originals[0].start_page,
            end_page=max(c.end_page for c in current_originals),
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


# Markdown 标题正则（用于子章节拆分）
_SUB_HEADING_PATTERN: re.Pattern[str] = re.compile(
    r"^(#{2,3})\s+(.+)$",
    re.MULTILINE,
)

# 中文子标题正则（支持编号后有/无空格两种情况）
_CN_SUB_HEADING_PATTERN: re.Pattern[str] = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+[、.]|[（(][一二三四五六七八九十\d]+[)）]|\d+\.\d+)\s*\S.*$",
    re.MULTILINE,
)


def _split_by_subheadings(
    text: str,
    chapter_path: list[str],
    page_range: tuple[int, int],
    *,
    max_tokens: int,
    overlap_tokens: int,
    sub_boundaries: list[ChapterBoundary] | None = None,
) -> list[Chunk] | None:
    """尝试按子标题拆分超长章节。

    拆分边界来源（按优先级）：
    1. **预检测边界**：若 sub_boundaries 非空，使用章节检测器提供的
       level≥2 子边界按页码范围切分文本
    2. **正则检测**：若无预检测边界，退回双通道正则检测

    Args:
        text: 章节 Markdown 文本。
        chapter_path: 当前章节路径。
        page_range: 章节页码范围。
        max_tokens: 单块最大 token 数。
        overlap_tokens: overlap token 数。
        sub_boundaries: 可选，章节检测器提供的 level≥2 子章节边界。

    Returns:
        Chunk 列表，或 None 表示无法按子标题拆分。
    """
    if sub_boundaries:
        # 使用预检测边界拆分（按页码范围）
        chunks: list[Chunk] = []
        texts = text.split("\n\n")

        current_text = ""
        current_sub_path: list[str] = []

        for boundary in sub_boundaries:
            # 提取该子边界范围内的文本
            sub_text_parts = []
            for page_idx in range(
                boundary.start_page - page_range[0],
                boundary.end_page - page_range[0] + 1,
            ):
                if 0 <= page_idx < len(texts):
                    sub_text_parts.append(texts[page_idx])

            sub_text = "\n\n".join(sub_text_parts)
            if not sub_text:
                continue

            if count_tokens(sub_text) <= max_tokens:
                chunks.append(
                    ChunkBuilder.create_chunk(
                        text=sub_text,
                        chapter_path=chapter_path + [boundary.title],
                        page_range=(boundary.start_page, boundary.end_page),
                        chunk_type=ChunkType.SUB_SECTION,
                        chunk_index=len(chunks),
                        needs_prior_summary=len(chunks) > 0,
                    )
                )
            else:
                # 超长子节：优先递归尝试更细粒度拆分
                sub_chunks = _split_by_subheadings(
                    text=sub_text,
                    chapter_path=chapter_path + [boundary.title],
                    page_range=(boundary.start_page, boundary.end_page),
                    max_tokens=max_tokens,
                    overlap_tokens=overlap_tokens,
                    sub_boundaries=None,  # 退回正则检测
                )
                if sub_chunks:
                    chunks.extend(sub_chunks)
                else:
                    # 正则检测也无法拆分，退回 token 窗口兜底
                    window_chunks = _split_by_token_window(
                        text=sub_text,
                        chapter_path=chapter_path + [boundary.title],
                        page_range=(boundary.start_page, boundary.end_page),
                        max_tokens=max_tokens,
                        overlap_tokens=overlap_tokens,
                    )
                    for j, wc in enumerate(window_chunks):
                        chunks.append(
                            ChunkBuilder.create_chunk(
                                text=wc.text,
                                chapter_path=chapter_path + [boundary.title],
                                page_range=wc.page_range,
                                chunk_type=ChunkType.TOKEN_WINDOW,
                                chunk_index=j,
                                needs_prior_summary=len(chunks) > 0,
                            )
                        )

        if chunks:
            return chunks

    # 退回正则检测
    # 按段落分割文本
    paragraphs = re.split(r"\n\n+", text)
    if len(paragraphs) <= 1:
        return None

    # 查找子标题位置
    heading_positions: list[tuple[int, str]] = []

    for i, para in enumerate(paragraphs):
        # Markdown 子标题
        match = _SUB_HEADING_PATTERN.match(para)
        if match:
            heading_positions.append((i, match.group(2).strip()))
            continue

        # 中文子标题
        if _CN_SUB_HEADING_PATTERN.match(para):
            # 提取标题部分（第一行）
            first_line = para.strip().split("\n")[0]
            heading_positions.append((i, first_line.strip()))
            continue

    if len(heading_positions) < 2:
        return None

    # 按子标题切分
    chunks: list[Chunk] = []
    for i, (pos, title) in enumerate(heading_positions):
        next_pos = (
            heading_positions[i + 1][0]
            if i + 1 < len(heading_positions)
            else len(paragraphs)
        )
        sub_text = "\n\n".join(paragraphs[pos:next_pos])

        if count_tokens(sub_text) <= max_tokens:
            chunks.append(
                ChunkBuilder.create_chunk(
                    text=sub_text,
                    chapter_path=chapter_path + [title],
                    page_range=page_range,
                    chunk_type=ChunkType.SUB_SECTION,
                    chunk_index=i,
                    needs_prior_summary=i > 0,
                )
            )
        else:
            # 超长子节退回 token 窗口
            window_chunks = _split_by_token_window(
                text=sub_text,
                chapter_path=chapter_path + [title],
                page_range=page_range,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )
            for j, wc in enumerate(window_chunks):
                chunks.append(
                    ChunkBuilder.create_chunk(
                        text=wc.text,
                        chapter_path=chapter_path + [title],
                        page_range=wc.page_range,
                        chunk_type=ChunkType.TOKEN_WINDOW,
                        chunk_index=j,
                        needs_prior_summary=(i > 0 or j > 0),
                    )
                )

    return chunks if chunks else None


def _split_by_token_window(
    text: str,
    chapter_path: list[str],
    page_range: tuple[int, int],
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """按 token 窗口 + overlap 切分文本。

    切分降级链：
    1. 按段落（\n\n）分割 - 优先在段落边界断开
    2. 单段落仍超限时按行（\n）分割 - 退而求其次
    3. 单行仍超限时硬截断 - 最后兜底

    Args:
        text: 待切分的 Markdown 文本。
        chapter_path: 章节路径。
        page_range: 页码范围。
        max_tokens: 单块最大 token 数。
        overlap_tokens: overlap token 数。

    Returns:
        Chunk 列表（至少一个元素）。
    """
    # 降级链尝试：段落 -> 行 -> 硬截断
    split_results = _split_oversized_paragraph(text, max_tokens, "\n\n")
    if split_results is None:
        # 段落分割失败（可能只有1个段落），尝试按行分割
        split_results = _split_oversized_paragraph(text, max_tokens, "\n")
        if split_results is None:
            # 行分割也失败（可能只有1行），直接硬截断
            return _hard_truncate_chunk(
                text, chapter_path, page_range, max_tokens, overlap_tokens
            )

    # 过滤并处理超长片段：每个片段不能超过 max_tokens
    processed_segments: list[str] = []
    for segment in split_results:
        seg_tokens = count_tokens(segment)
        if seg_tokens <= max_tokens:
            processed_segments.append(segment)
        else:
            # 片段本身超限，需要硬截断
            truncated = truncate_to_tokens(segment, max_tokens)
            processed_segments.append(truncated)

    if not processed_segments:
        return _hard_truncate_chunk(
            text, chapter_path, page_range, max_tokens, overlap_tokens
        )

    # 根据分割结果构建 chunks，处理 overlap
    chunks: list[Chunk] = []
    chunk_index = 0

    for i, segment in enumerate(processed_segments):
        if i == 0:
            # 第一个片段，直接添加
            chunks.append(
                ChunkBuilder.create_chunk(
                    text=segment,
                    chapter_path=chapter_path,
                    page_range=page_range,
                    chunk_type=ChunkType.TOKEN_WINDOW,
                    chunk_index=chunk_index,
                    needs_prior_summary=False,
                )
            )
            chunk_index += 1
        else:
            # 后续片段，添加 overlap
            # 注意：full_text 的 token 数应 <= max_tokens，需要从 segment 中预留 overlap 空间
            prev_text = chunks[i - 1].text
            overlap_text = truncate_to_tokens(prev_text, overlap_tokens)
            overlap_token_count = count_tokens(overlap_text)

            # 从 segment 中截取，预留 overlap 空间
            available_tokens = max_tokens - overlap_token_count - 1  # -1 for newline
            if available_tokens > 0:
                segment_with_space = truncate_to_tokens(segment, available_tokens)
            else:
                segment_with_space = ""

            full_text = (
                overlap_text + "\n" + segment_with_space
                if overlap_text
                else segment_with_space
            )

            chunks.append(
                ChunkBuilder.create_chunk(
                    text=full_text,
                    chapter_path=chapter_path,
                    page_range=page_range,
                    chunk_type=ChunkType.TOKEN_WINDOW,
                    chunk_index=chunk_index,
                    needs_prior_summary=True,
                )
            )
            chunk_index += 1

    return chunks


def _hard_truncate_chunk(
    text: str,
    chapter_path: list[str],
    page_range: tuple[int, int],
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """硬截断超长文本，返回单个 chunk。

    Args:
        text: 待截断文本。
        chapter_path: 章节路径。
        page_range: 页码范围。
        max_tokens: 最大 token 数。
        overlap_tokens: overlap token 数（此函数不使用）。

    Returns:
        单个 Chunk。
    """
    truncated = truncate_to_tokens(text, max_tokens)
    return [
        ChunkBuilder.create_chunk(
            text=truncated,
            chapter_path=chapter_path,
            page_range=page_range,
            chunk_type=ChunkType.TOKEN_WINDOW,
            chunk_index=0,
            needs_prior_summary=False,
        )
    ]


def _split_oversized_paragraph(
    text: str,
    max_tokens: int,
    sep: str,
) -> list[str] | None:
    """按分隔符分割文本，贪婪合并使每个片段 <= max_tokens。

    算法：
    1. 按分隔符分割成原始片段
    2. 贪婪地合并相邻片段，直到达到 max_tokens
    3. 返回合并后的片段列表

    Args:
        text: 待分割的文本。
        max_tokens: 最大 token 数。
        sep: 分隔符（如 "\n\n" 或 "\n"）。

    Returns:
        片段列表（每个 <= max_tokens），或 None 表示无法分割。
    """
    raw_segments = re.split(sep + r"+", text)
    if len(raw_segments) <= 1:
        return None

    # 贪婪合并相邻片段
    result: list[str] = []
    current_segment = ""
    current_tokens = 0

    for seg in raw_segments:
        seg_tokens = count_tokens(seg)

        if not current_segment:
            # 第一个片段
            if seg_tokens <= max_tokens:
                current_segment = seg
                current_tokens = seg_tokens
            else:
                # 第一个片段就超限，需要降级
                return None
            continue

        # 检查加入新片段后是否超限
        if current_tokens + seg_tokens <= max_tokens:
            # 合并
            current_segment += sep + seg
            current_tokens += seg_tokens
        else:
            # 保存当前片段，开始新的
            result.append(current_segment)
            current_segment = seg
            current_tokens = seg_tokens

    # 保存最后一个片段
    if current_segment:
        result.append(current_segment)

    if not result:
        return None

    return result
