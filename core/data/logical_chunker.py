"""逻辑分块主入口模块。

将 Step 1 的 ParsedDocument 通过章节识别 + 分块引擎 + 持久化
完成端到端的逻辑分块流程。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

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
    ...
