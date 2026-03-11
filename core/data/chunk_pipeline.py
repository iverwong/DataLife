"""逻辑分块主入口模块。

将 Step 1 的 ParsedDocument 通过章节识别 + 分块引擎 + 持久化
完成端到端的逻辑分块流程。
"""

from __future__ import annotations

import logfire
import pymupdf

from core.data.chapter_detector import detect_chapters
from core.data.chunk_storage import save_chunks
from core.data.chunker import build_chunks, split_text_by_token_window
from core.data.models import Chunk, ChunkList, ChunkType, ParsedDocument, TextSegment
from core.data.token_counter import count_tokens

# 直通阈值倍数
BYPASS_THRESHOLD_FACTOR: int = 3


def _build_bypass_chunk_list(
    parsed: ParsedDocument,
    segments: list[TextSegment],
    *,
    overlap_tokens: int,
) -> ChunkList:
    """将 TextSegment 列表包装为 ChunkList（直通路径专用）。

    每个 TextSegment 包装为一个 TOKEN_WINDOW 类型的 Chunk，
    chapter_path 为空（交给 LLM 在摘要阶段识别章节），
    page_range 覆盖整个文档。

    Args:
        parsed: 原始 ParsedDocument。
        segments: split_text_by_token_window 产出的分段列表。
        overlap_tokens: overlap token 数（用于日志）。

    Returns:
        ChunkList 对象。
    """
    raise NotImplementedError


async def chunk_document(
    content: bytes,
    parsed: ParsedDocument,
    *,
    stock_code: str = "",
    report_date: str = "",
    max_tokens: int = 8000,
    persist: bool = True,
) -> ChunkList:
    """对已解析的文档执行逻辑分块。

    完整流程：
    1. 打开 PDF 获取书签等原始信息
    2. 调用章节识别（多级降级）
    3. 调用分块引擎产出 ChunkList
    4. 可选：持久化到本地

    Args:
        content: PDF 文件的原始字节流。
        parsed: Step 1 产出的 ParsedDocument。
        stock_code: 股票代码（用于持久化路径）。
        report_date: 报告日期（用于持久化路径）。
        max_tokens: 单个 Chunk 的最大 token 数。
        persist: 是否持久化结果。

    Returns:
        ChunkList 对象。
    """
    doc: pymupdf.Document | None = None
    try:
        # Step 1: 打开 PDF
        doc = pymupdf.open(stream=content, filetype="pdf")

        # Step 2: 直通检查（整体长度小于3倍max_token的直接拆分）
        perid = count_tokens(parsed.full_text) // max_tokens
        if perid < 3:
            # 按max_token截断

            pass

        # Step 3: 调用章节识别（多级降级）
        logfire.debug(
            "开始章节识别: source={source}, pages={page_count}",
            source=parsed.source,
            page_count=parsed.page_count,
        )
        chapters = detect_chapters(doc, parsed)
        logfire.info(
            "章节识别完成: chapter_count={count}, source={source}",
            count=len(chapters),
            source=parsed.source,
        )

        # FIX 这部分的逻辑没有检查的，感觉有问题
        # Step 4: 调用分块引擎产出 ChunkList
        chunk_list = build_chunks(parsed, chapters, max_tokens=max_tokens)
        logfire.info(
            "分块完成: source={source}, chunk_count={chunk_count}, total_tokens={total_tokens}, chapter_count={chapter_count}",
            source=parsed.source,
            chunk_count=len(chunk_list.chunks),
            total_tokens=chunk_list.total_tokens,
            chapter_count=chunk_list.chapter_count,
        )

        # Step 5: 持久化
        if persist and stock_code and report_date:
            await save_chunks(
                chunk_list,
                stock_code=stock_code,
                report_date=report_date,
            )
            logfire.debug(
                "分块结果已持久化: stock={stock}, date={date}",
                stock=stock_code,
                date=report_date,
            )

        return chunk_list
    finally:
        # 确保关闭文档
        if doc is not None:
            doc.close()
