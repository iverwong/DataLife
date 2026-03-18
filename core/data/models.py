"""内部领域数据模型。

包含逻辑分块流程中使用的 dataclass 和类型别名。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class ChunkType(enum.Enum):
    """分块类型标识。

    Attributes:
        COMPLETE_CHAPTER: 完整章节，未经二次拆分。
        SUB_SECTION: 按子章节（##、###）拆分的子块。
        TOKEN_WINDOW: 纯 token 窗口兜底切分的子块。
    """

    COMPLETE_CHAPTER = "complete_chapter"
    SUB_SECTION = "sub_section"
    TOKEN_WINDOW = "token_window"


@dataclass(frozen=True)
class ChapterBoundary:
    """章节边界信息。

    由章节识别模块产出，描述一个章节在文档中的位置。

    Attributes:
        title: 章节标题。
        level: 章节层级（1 为顶级章节）。
        start_page: 起始页码（1-based，含）。
        end_page: 结束页码（1-based，含）。
        source: 识别来源，取值 "bookmark" | "toc_page" | "heading" | "fallback"。
    """

    title: str
    level: int
    start_page: int
    end_page: int
    source: str


@dataclass(frozen=True)
class MergedChapter:
    """合并后的章节信息，包含原始章节列表。

    Attributes:
        chapter: 合并后的章节边界。
        original_chapters: 原始章节列表（用于追溯被合并的章节）。
    """

    chapter: ChapterBoundary
    original_chapters: list[ChapterBoundary]


@dataclass(frozen=True)
class ChunkMeta:
    """被合并进 Chunk 的原始章节摘要信息。

    用于记录同页合并等场景下，一个 Chunk 实际包含了哪些原始章节。
    LLM 摘要时可据此对各章节分别产出结构化摘要，避免对不完整章节
    产生模糊总结。

    Attributes:
        title: 原始章节标题。
        level: 章节层级。
        page_range: 章节页码范围 (start, end)，1-based，含。
    """

    title: str
    level: int
    page_range: tuple[int, int]


@dataclass(frozen=True)
class Chunk:
    """逻辑分块结果。

    每个 Chunk 对应一个可独立送入 LLM 摘要的文本块。

    Attributes:
        text: 该章节/子块的 Markdown 文本。
        chapter_path: 章节路径，如 ["第一节 重要提示", "一、重要提示"]。
        page_range: PDF 页码范围 (start, end)，1-based，含。
        token_count: 该块的 token 数（tiktoken 计算）。
        chunk_type: 分块类型。
        needs_prior_summary: 是否需要注入前一章/前一子块的摘要作为上下文。
        chunk_index: 在同一章节内的子块序号（0-based），完整章节为 0。
        contained_chapters: 该 Chunk 包含的原始章节列表。
            单章节时为 [自身]；同页合并时记录所有被合并的原始章节。
            LLM 摘要 prompt 可注入此信息，使其按章节分别产出摘要，
            避免对不完整或混合章节做模糊总结。
    """

    text: str
    chapter_path: list[str]
    page_range: tuple[int, int]
    token_count: int
    chunk_type: ChunkType
    needs_prior_summary: bool = False
    chunk_index: int = 0
    contained_chapters: list[ChunkMeta] = field(default_factory=list)
    chapter_hierarchy: list[ChapterPathEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ChapterPathEntry:
    """章节路径条目，携带层级信息。

    用于替代 chapter_path 中的纯字符串，使 LLM 能区分
    嵌套层级（level 1 > level 2）与同级合并（level 1 + level 1）。

    Attributes:
        title: 章节标题。
        level: 章节层级（1 为顶级）。
    """

    title: str
    level: int


@dataclass(frozen=True)
class ChunkList:
    """分块结果集合。

    Attributes:
        source: 来源标识，格式为 "{stock_code}/{report_date}"，如 "300274/2024-annual"。
        chunks: 按文档顺序排列的 Chunk 列表。
        total_tokens: 所有块的 token 总数。
        chapter_count: 识别出的章节数。
    """

    source: str
    chunks: list[Chunk]
    total_tokens: int
    chapter_count: int


@dataclass(frozen=True)
class PageChunk:
    """单页解析结果。

    Attributes:
        page_number: 1-based 页码（方便自然理解）。
            注意：pymupdf4llm 返回 0-based，由 _parse_document() 转换为 1-based。
        markdown_text: 该页的 Markdown 文本（Layout 模式下已包含表格格式化）。
        metadata: 文档元数据，包含 file_path、page_count、page_number 等。
        toc_items: 指向该页的目录项列表，格式 [lvl, title, pagenumber(1-based)]。
        page_boxes: Layout 布局边界框列表，每项含 index / class / bbox / pos。
            class 可为 "text" / "title" / "table" / "picture" / "header" / "footer" 等。
            pos 为 tuple(start, stop)，用于从 markdown_text 中切片提取该区域文本。
    """

    page_number: int
    markdown_text: str
    metadata: dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportExplicitAny]
    toc_items: list[list[Any]] = field(default_factory=list)  # pyright: ignore[reportExplicitAny]
    page_boxes: list[dict[str, Any]] = field(default_factory=list)  # pyright: ignore[reportExplicitAny]


@dataclass(frozen=True)
class PDFParseResult:
    """PDF 解析的完整结果。

    Attributes:
        source: 来源标识（文件路径字符串或自定义名称），用于日志和下游追溯。
        page_count: PDF 总页数。
        chunks: 按页分块的解析结果列表，顺序与原始页码一致。
    """

    source: str
    page_count: int
    chunks: list[PageChunk] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """拼接所有页面的 Markdown 文本，页间以双换行分隔。"""
        return "\n\n".join(chunk.markdown_text for chunk in self.chunks)


# 类型别名（复用 Step 1 的解析结果）
ParsedPage = PageChunk
"""单页解析结果，等价于 Step 1 的 PageChunk。"""

ParsedDocument = PDFParseResult
"""完整文档解析结果，等价于 Step 1 的 PDFParseResult。"""
