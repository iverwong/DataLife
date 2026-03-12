"""逻辑分块主入口模块。

将 Step 1 的 ParsedDocument 通过章节识别 + 分块引擎 + 持久化
完成端到端的逻辑分块流程。
"""

from __future__ import annotations

import logfire
import pymupdf

from core.data.chapter_detector import detect_chapters
from core.data.chunk_storage import save_chunks
from core.data.chunker import build_chunks
from core.data.exceptions import InvalidChunkingParameterError
from core.data.models import Chunk, ChunkList, ChunkType, ParsedDocument
from core.data.token_indexer import (
    encode_pages_incremental,
    slice_window_from_index,
)

# 直通阈值倍数
BYPASS_THRESHOLD_FACTOR: int = 3

# overlap重叠token数
OVERLAP_TOKENS = 200

# 单个 Chunk 的最大 token 数
DEFAULT_MAX_TOKENS: int = 8000


async def chunk_document(
    content: bytes,
    parsed: ParsedDocument,
    *,
    stock_code: str = "",
    report_date: str = "",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
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
        overlap_tokens: 相邻 chunk 之间的重叠 token 数。
        persist: 是否持久化结果。

    Returns:
        ChunkList 对象。

    Raises:
        InvalidChunkingParameterError: 当 overlap_tokens >= max_tokens 时抛出。
    """
    # 参数校验：overlap_tokens >= max_tokens 会导致无限循环
    if overlap_tokens >= max_tokens:
        raise InvalidChunkingParameterError(
            f"overlap_tokens ({overlap_tokens}) must be less than max_tokens ({max_tokens})"
        )

    doc: pymupdf.Document | None = None
    try:
        # Step 1: 打开 PDF
        doc = pymupdf.open(stream=content, filetype="pdf")

        # Step 2: 直通检查（整体长度小于3倍max_token的直接拆分）
        # 使用 token_indexer 池化编码，如果文档小于阈值则直接切窗口
        token_index = encode_pages_incremental(
            parsed, threshold=BYPASS_THRESHOLD_FACTOR * max_tokens
        )

        if token_index is not None:
            # 直通路径：使用 token ID 池切窗口，跳过章节识别
            chunks: list[Chunk] = []
            start = 0

            while start < token_index.total_tokens:
                # 切取窗口
                text, actual_tokens, page_range = slice_window_from_index(
                    index=token_index,
                    start=start,
                    length=max_tokens,
                )

                # 构建 Chunk
                chunk = Chunk(
                    text=text,
                    chapter_path=[],
                    page_range=page_range,
                    token_count=actual_tokens,
                    chunk_type=ChunkType.TOKEN_WINDOW,
                )
                chunks.append(chunk)

                # 移动窗口（考虑 overlap）
                start += max_tokens - overlap_tokens

            # 计算总 token 数
            total_token_count = sum(c.token_count for c in chunks)

            chunk_list = ChunkList(
                source=parsed.source,
                chunks=chunks,
                total_tokens=total_token_count,
                chapter_count=0,  # 直通路径不识别章节
            )

            # 记录日志
            logfire.info(
                "直通路径: source={source}, total_tokens={total}, chunks={count}",
                source=parsed.source,
                total=total_token_count,
                count=len(chunks),
            )

            # 执行持久化（如果需要）
            if persist and stock_code and report_date:
                await save_chunks(
                    chunk_list,
                    stock_code=stock_code,
                    report_date=report_date,
                )

            return chunk_list

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

        # Step 4: 调用分块引擎产出 ChunkList
        chunk_list = build_chunks(
            parsed,
            chapters,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
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
