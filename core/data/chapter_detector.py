"""章节识别模块。

采用多信号融合、逐级降级策略，从 PDF 中识别章节边界。
降级顺序：PDF 书签 → 目录页解析 → Markdown 标题检测 → 纯 token 窗口兜底。

职责边界：
- 本模块只负责「识别章节边界」
- 不负责按章节切分文本（由 chunker 模块负责）
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, cast, override

import pymupdf

from core.data.models import ChapterBoundary, ParsedDocument


class ChapterDetectionStrategy(ABC):
    """章节检测策略的抽象基类。

    每种策略实现一种章节识别方式。
    detect 方法返回 None 表示该策略无法识别，触发降级。
    """

    @abstractmethod
    def detect(
        self,
        doc: pymupdf.Document,
        parsed: ParsedDocument,
    ) -> list[ChapterBoundary] | None:
        """尝试从文档中识别章节边界。

        Args:
            doc: 已打开的 PyMuPDF Document 对象。
            parsed: Step 1 产出的 ParsedDocument。

        Returns:
            章节边界列表，按页码升序排列。
            返回 None 表示该策略无法识别有效章节，应降级到下一策略。
        """
        ...


class BookmarkStrategy(ChapterDetectionStrategy):
    """Level 1：基于 PDF 书签（TOC）的章节识别。

    从 doc.get_toc() 提取**所有层级**的书签结构，保留层级信息。
    验证书签指向的页码是否真正对应章节起始（通过检查对应页面的
    Markdown 文本中是否存在匹配的标题文本，模糊匹配）。

    多层级处理策略：
    - 保留所有层级的书签（level=1 为顶级，level=2 为子章节如 1.1）
    - 将 level 直接映射到 ChapterBoundary.level
    - chunker 模块根据 level 决定分块粒度：
       level=1 的章节作为主分块边界，level≥2 的子章节用于超长章节的二次拆分

    验证失败的书签会被过滤，若有效书签不足 2 个则返回 None 触发降级。
    """

    @override
    def detect(
        self,
        doc: pymupdf.Document,
        parsed: ParsedDocument,
    ) -> list[ChapterBoundary] | None:
        # 获取书签列表
        toc: list[list[Any]] = doc.get_toc()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportExplicitAny]
        if not toc:
            return None

        # 转换为页码索引（0-based）
        boundaries: list[ChapterBoundary] = []

        for toc_entry in toc:
            # toc_entry 格式: [level, title, page_number, ...]
            # page_number 是 1-based
            level = cast(int, toc_entry[0])
            title = cast(str, toc_entry[1])
            page_number = cast(int, toc_entry[2])

            # 只保留 level 1-2 的书签
            if level > 2:
                continue

            # 跳过无效页码
            if page_number < 1 or page_number > parsed.page_count:
                continue

            # 验证书签：检查对应页面是否包含匹配的标题文本
            # level 1: 必须验证书签标题与页面内容匹配
            # level 2: 跳过验证（子章节标题可能与父章节标题不同，但位于同一页面）
            page_index = page_number - 1
            if level == 1 and page_index < len(parsed.chunks):
                page_text = parsed.chunks[page_index].markdown_text
                # 模糊匹配：去除空格后比较
                normalized_title = title.replace(" ", "").replace("\u3000", "")
                normalized_page = (
                    page_text.replace(" ", "").replace("\n", "").replace("\u3000", "")
                )

                if normalized_title not in normalized_page:
                    continue  # 跳过该条，不整批降级

            # 创建边界
            boundary = ChapterBoundary(
                title=title,
                level=level,
                start_page=page_number,
                end_page=page_number,  # 临时值，后续计算
                source="bookmark",
            )
            boundaries.append(boundary)

        # 有效书签不足 2 个则返回 None
        if len(boundaries) < 2:
            return None

        # 计算每个章节的 end_page（下一个同级或更高级书签的 start_page - 1）
        result: list[ChapterBoundary] = []
        for i, boundary in enumerate(boundaries):
            # 找到下一个同级或更高级的书签
            next_start = parsed.page_count + 1  # 默认到文档末尾
            for j in range(i + 1, len(boundaries)):
                if boundaries[j].level <= boundary.level:
                    next_start = boundaries[j].start_page
                    break

            end_page = next_start - 1

            # 创建新的 ChapterBoundary（因为 frozen dataclass 不能修改）
            result.append(
                ChapterBoundary(
                    title=boundary.title,
                    level=boundary.level,
                    start_page=boundary.start_page,
                    end_page=max(
                        end_page, boundary.start_page
                    ),  # 如同页的话，那么直接取当前页就行了
                    source=boundary.source,
                )
            )

        return result


class TocPageStrategy(ChapterDetectionStrategy):
    """Level 2：基于目录页解析的章节识别。

    检测 PDF 前 N 页中是否存在「目录」页（通过关键词 + 格式特征识别），
    从中提取章节名称和对应页码。

    处理 PDF 页码 vs 文档印刷页码的偏移（如 PDF 第 5 页印刷为「第 1 页」）。
    """

    # 目录页检测正则（支持任意空格："目录"、"目 录"、"目  录" 等）
    TOC_PATTERN: re.Pattern[str] = re.compile(
        r"目\s*录|CONTENTS|Table\s+of\s+Contents", re.IGNORECASE
    )
    # 目录项提取正则：匹配 "章节名 ....... 页码"
    TOC_ENTRY_PATTERN: re.Pattern[str] = re.compile(
        r"^(.+?)\s*[.…·\-_]{3,}\s*(\d+(?:\s+\d+)*)\s*$",
        re.MULTILINE,
    )
    # 紧凑目录项正则：匹配同一行内的 "章节名 ....... 页码" 模式
    TOC_COMPACT_PATTERN: re.Pattern[str] = re.compile(
        r"((?:[第]\S+[节章]\s+)?\S{2,30})\s*[.…·\-_]{3,}\s*(\d+)"
    )
    # 搜索目录的最大页数范围
    MAX_SEARCH_PAGES: int = 10

    @override
    def detect(
        self,
        doc: pymupdf.Document,
        parsed: ParsedDocument,
    ) -> list[ChapterBoundary] | None:
        # 查找目录页
        toc_page_idx: int | None = None
        for i in range(min(self.MAX_SEARCH_PAGES, parsed.page_count)):
            page_text = parsed.chunks[i].markdown_text
            if self.TOC_PATTERN.search(page_text):
                toc_page_idx = i
                break

        if toc_page_idx is None:
            return None

        # 提取目录项
        toc_page_text = parsed.chunks[toc_page_idx].markdown_text
        entries: list[tuple[str, int]] = []

        # 优先尝试多行格式
        for match in self.TOC_ENTRY_PATTERN.finditer(toc_page_text):
            title = match.group(1).strip()
            page_num = int(
                re.sub(r"\s+", "", match.group(2))
            )  # 增加了捕获和处理页码中间有空格的情况
            entries.append((title, page_num))

        # 多行格式不足 2 项时，尝试紧凑格式
        if len(entries) < 2:
            entries = []
            for match in self.TOC_COMPACT_PATTERN.finditer(toc_page_text):
                title = match.group(1).strip()
                page_num = int(match.group(2))
                # 页码范围预过滤：排除明显不合理的页码，降低误匹配风险
                if 1 <= page_num <= parsed.page_count:
                    entries.append((title, page_num))

        if len(entries) < 2:
            return None

        # 用页脚计算偏移：取 PDF 最后几页，从页脚提取印刷页码
        _FOOTER_PATTERN: re.Pattern[str] = re.compile(
            r"(?<!\d)(\d{1,3})(?:\s*/\s*(\d{1,3}))?(?!\d)", re.MULTILINE
        )
        offset: int | None = None
        max_page = parsed.page_count

        # 搜索最后 3 页的页脚
        for pdf_page_idx in range(
            parsed.page_count - 1, max(0, parsed.page_count - 4), -1
        ):
            page_chunk = parsed.chunks[pdf_page_idx]
            # 从 markdown 最后几行提取页脚
            lines = page_chunk.markdown_text.strip().split("\n")
            footer_lines = lines[-5:]  # 取最后 5 行
            pdf_page = pdf_page_idx + 1

            for line in footer_lines:
                match = _FOOTER_PATTERN.search(line.strip())
                if match:
                    footer_page = int(match.group(1))
                    total_from_footer = match.group(2)

                    # 合理性检查：页码应该接近总页数
                    if abs(footer_page - max_page) > 15:
                        continue

                    # 如果有 /Y 格式，检查 X 和 Y 是否一致（仅对最后一页有意义）
                    if total_from_footer is not None:
                        total_page = int(total_from_footer)
                        # 如果是最后一页，X 和 Y 应该一致
                        if pdf_page == max_page and footer_page != total_page:
                            continue

                    # 计算偏移：印刷页码 - PDF 页码
                    offset = footer_page - pdf_page
                    break
            if offset is not None:
                break

        if offset is None:
            # 无法确定偏移，使用 0
            offset = 0

        # 转换印刷页码为 PDF 页码，并过滤有效范围
        boundaries: list[ChapterBoundary] = []
        for title, printed_page in entries:
            pdf_page = printed_page - offset
            if 1 <= pdf_page <= parsed.page_count:
                boundaries.append(
                    ChapterBoundary(
                        title=title,
                        level=1,  # 目录页解析默认 level=1
                        start_page=pdf_page,
                        end_page=pdf_page,  # 临时值
                        source="toc_page",
                    )
                )

        if len(boundaries) < 2:
            return None

        # 计算 end_page（所有 level=1，直接取下一个边界）
        result: list[ChapterBoundary] = []
        for i, boundary in enumerate(boundaries):
            if i + 1 < len(boundaries):
                end_page = boundaries[i + 1].start_page - 1
            else:
                end_page = parsed.page_count  # 最后一章到文档末尾

            result.append(
                ChapterBoundary(
                    title=boundary.title,
                    level=boundary.level,
                    start_page=boundary.start_page,
                    end_page=max(end_page, boundary.start_page),
                    source=boundary.source,
                )
            )

        return result


class HeadingStrategy(ChapterDetectionStrategy):
    """Level 3：基于 Markdown 标题标记 + 中文编号模式的章节识别。

    当书签和目录都不可用时，退回到文本特征检测：
    1. Markdown 标题标记（#、##、###）
    2. 中文财报常见编号模式：
       - 「第一节 重要提示」「第2章 公司概况」
       - 「一、公司基本情况」「二、主要业务」
       - 「（一）主要产品」「（二）经营模式」
       - 「1、产品概况」「2.1 产品分类」「1.1 背景」
    结合 toc_items 中的层级信息做交叉验证。
    保留所有层级标题（与 BookmarkStrategy 行为对齐），level 映射规则：
    - Markdown: # → level=1, ## → level=2, ### → level=3
    - 中文编号: 第X节/章 → level=1, 一、二、 → level=2, （一）/1.1 → level=3
    chunker 模块根据 level 信息决定分块粒度。
    """

    # Markdown 标题检测正则
    MARKDOWN_HEADING_PATTERN: re.Pattern[str] = re.compile(
        r"^(#{1,2})\s+(.+)$",
        re.MULTILINE,
    )

    @override
    def detect(
        self,
        doc: pymupdf.Document,
        parsed: ParsedDocument,
    ) -> list[ChapterBoundary] | None:
        boundaries: list[ChapterBoundary] = []

        # 遍历所有页面
        for page in parsed.chunks:
            page_text = page.markdown_text
            page_number = page.page_number

            # Markdown 标题检测
            for match in self.MARKDOWN_HEADING_PATTERN.finditer(page_text):
                level = len(match.group(1))  # # → 1, ## → 2, ### → 3
                title = match.group(2).strip()
                boundaries.append(
                    ChapterBoundary(
                        title=title,
                        level=level,
                        start_page=page_number,
                        end_page=page_number,  # 临时值
                        source="heading",
                    )
                )

        if len(boundaries) < 2:
            return None

        # 计算 end_page
        result: list[ChapterBoundary] = []
        for i, boundary in enumerate(boundaries):
            next_start = parsed.page_count + 1
            for j in range(i + 1, len(boundaries)):
                if boundaries[j].level <= boundary.level:
                    next_start = boundaries[j].start_page
                    break
            end_page = next_start - 1

            result.append(
                ChapterBoundary(
                    title=boundary.title,
                    level=boundary.level,
                    start_page=boundary.start_page,
                    end_page=max(end_page, boundary.start_page),
                    source=boundary.source,
                )
            )

        return result


class FallbackStrategy(ChapterDetectionStrategy):
    """Level 4：全文兜底策略。

    当以上策略全部失败时，将整篇文档作为单一章节返回。
    实际的 token 窗口切分由 chunker 模块的 _split_by_token_window 负责。

    职责边界：
    - 本策略只负责返回一个覆盖全文的 ChapterBoundary
    - 不做 token 计数或窗口切分（避免与 chunker 职责重叠）
    - 此策略始终成功，不返回 None
    """

    @override
    def detect(
        self,
        doc: pymupdf.Document,
        parsed: ParsedDocument,
    ) -> list[ChapterBoundary]:
        # 返回覆盖全文的单一章节
        return [
            ChapterBoundary(
                title="全文",
                level=1,
                start_page=1,
                end_page=parsed.page_count,
                source="fallback",
            )
        ]


def detect_chapters(
    doc: pymupdf.Document,
    parsed: ParsedDocument,
) -> list[ChapterBoundary]:
    """使用多级降级策略识别文档的章节边界。

    按优先级依次尝试：书签 → 目录页 → Markdown 标题 → 全文兜底。
    首个返回非 None 结果的策略生效。

    Args:
        doc: 已打开的 PyMuPDF Document 对象。
        parsed: Step 1 产出的 ParsedDocument。

    Returns:
        章节边界列表，按页码升序排列，至少包含一个条目。
    """
    strategies: list[ChapterDetectionStrategy] = [
        BookmarkStrategy(),
        TocPageStrategy(),
        HeadingStrategy(),
        FallbackStrategy(),
    ]

    for strategy in strategies:
        result = strategy.detect(doc, parsed)
        if result is not None:
            return result

    # 不应该到达这里 - FallbackStrategy 已返回结果，此处是防御性代码
    raise RuntimeError("章节检测循环应包括兜底策略")
