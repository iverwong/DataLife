"""逻辑分块主入口模块。

将 Step 1 的 ParsedDocument 通过章节识别 + 分块引擎 + 持久化
完成端到端的逻辑分块流程。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import logfire

from core.data.models import ParsedDocument, ChunkList
from core.data.chapter_detector import detect_chapters
from core.data.chunker import build_chunks
from core.data.chunk_storage import save_chunks


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
        # Step 1: 打开 PDF 获取书签等原始信息
        doc = pymupdf.open(stream=content, filetype="pdf")

        # Step 2: 调用章节识别（多级降级）
        logfire.debug("开始章节识别: source={source}, pages={page_count}",
                      source=parsed.source, page_count=parsed.page_count)
        chapters = detect_chapters(doc, parsed)
        logfire.info("章节识别完成: chapter_count={count}, source={source}",
                     count=len(chapters), source=parsed.source)

        # Step 3: 调用分块引擎产出 ChunkList
        chunk_list = build_chunks(parsed, chapters, max_tokens=max_tokens)
        logfire.info(
            "分块完成: source={source}, chunk_count={chunk_count}, "
            "total_tokens={total_tokens}, chapter_count={chapter_count}",
            source=parsed.source,
            chunk_count=len(chunk_list.chunks),
            total_tokens=chunk_list.total_tokens,
            chapter_count=chunk_list.chapter_count,
        )

        # Step 4: 可选持久化
        if persist and stock_code and report_date:
            await save_chunks(
                chunk_list,
                stock_code=stock_code,
                report_date=report_date,
            )
            logfire.debug("分块结果已持久化: stock={stock}, date={date}",
                          stock=stock_code, date=report_date)

        return chunk_list
    finally:
        # 确保关闭文档
        if doc is not None:
            doc.close()
