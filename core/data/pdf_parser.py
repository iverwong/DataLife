"""PDF → Markdown 解析模块。

使用 pymupdf4llm + PyMuPDF Layout 将文本型 PDF 转换为结构化 Markdown，
为后续分块和摘要做准备。

职责边界：
- 本模块只负责「内容提取」（PDF → Markdown）
- 物理分割（大文件按页拆分为子 PDF）仍由 pdf_split.py 负责
- 逻辑分块（Markdown → token 块）由 Step 2 模块负责

Layout 模式说明：
- 必须在 import pymupdf4llm 之前 import pymupdf.layout 以激活
- Layout 启用后，以下普通模式参数被忽略：
  table_strategy / margins / fontsize_limit / graphics_limit /
  hdr_info / image_size_limit / ignore_images / ignore_graphics /
  ignore_alpha / detect_bg_color / extract_words / use_glyphs
- Layout 通过 ML 模型自动识别：页眉页脚、表格、标题层级、布局区域
- Layout 新增参数：header / footer / use_ocr / ocr_language 等
"""

from __future__ import annotations

import pymupdf.layout  # noqa: F401 — 激活 Layout 模式，必须在 pymupdf4llm 之前
import pymupdf  # noqa: E402
import pymupdf4llm  # noqa: E402

import asyncio
from pathlib import Path

import logfire

from core.exceptions import DataLifeError
from core.data.models import PageChunk, PDFParseResult

# ── 异常 ─────────────────────────────────────────────


class PDFParsingError(DataLifeError):
    """PDF 解析过程中的基础异常。"""


class PDFFileNotFoundError(PDFParsingError):
    """PDF 文件路径不存在。"""


class PDFEncryptedError(PDFParsingError):
    """PDF 文件已加密且无法打开。"""


class PDFCorruptedError(PDFParsingError):
    """PDF 文件损坏或格式无效，无法解析。"""


# ── 常量 ─────────────────────────────────────────────
DEFAULT_OCR_LANGUAGE: str = "chi_sim+eng"
"""默认 OCR 语言：简体中文 + 英文（财报场景）。"""

# ── 数据结构定义在 core/data/models.py（见 4.4 节） ────

# ── 核心函数 ──────────────────────────────────────────
async def parse_pdf(
    pdf_path: str | Path,
    *,
    pages: list[int] | None = None,
    include_header_footer: bool = False,
) -> PDFParseResult:
    """将 PDF 文件解析为结构化 Markdown。

    使用 PyMuPDF Layout 模式，自动识别表格、标题层级和布局区域。
    默认过滤页眉页脚。

    内部通过 asyncio.to_thread() 将同步的 pymupdf4llm 调用
    放入线程池执行，避免阻塞事件循环。

    Args:
        pdf_path: PDF 文件路径，支持 str 或 Path。内部统一转为 Path。
        pages: 要处理的页码列表（0-based，传给 pymupdf4llm），None 表示全部页面。
            注意：返回结果中的 page_number 为 1-based（方便自然理解）。
        include_header_footer: 是否保留页眉页脚，默认 False（过滤）。
            对应 Layout 的 header / footer 参数。

    Returns:
        PDFParseResult 包含按页分块的解析结果。

    Raises:
        PDFFileNotFoundError: 文件路径不存在。
        PDFEncryptedError: PDF 已加密且无法打开。
        PDFCorruptedError: PDF 文件损坏或格式无效。
        PDFParsingError: 其它解析错误。
    """
    ...


async def parse_pdf_bytes(
    pdf_bytes: bytes,
    *,
    source: str = "unknown.pdf",
    pages: list[int] | None = None,
    include_header_footer: bool = False,
) -> PDFParseResult:
    """从内存字节流解析 PDF。

    用于从网络下载后直接解析而不落盘的场景（如巨潮/东财公告下载）。
    内部通过 asyncio.to_thread() 将同步的 pymupdf4llm 调用
    放入线程池执行，避免阻塞事件循环。

    Args:
        pdf_bytes: PDF 文件的字节内容。
        source: 来源标识（文件名或公告标题），用于日志和元信息。
        pages: 要处理的页码列表（0-based，传给 pymupdf4llm），None 表示全部。
            注意：返回结果中的 page_number 为 1-based。
        include_header_footer: 是否保留页眉页脚，默认 False。

    Returns:
        PDFParseResult 包含按页分块的解析结果。

    Raises:
        PDFCorruptedError: 字节内容为空或非有效 PDF。
        PDFEncryptedError: PDF 已加密。
        PDFParsingError: 其它解析错误。
    """
    ...


def _parse_document(
    doc: pymupdf.Document,
    *,
    source: str,
    pages: list[int] | None = None,
    include_header_footer: bool = False,
) -> PDFParseResult:
    """内部共享解析逻辑（同步）。

    由 parse_pdf 和 parse_pdf_bytes 通过 asyncio.to_thread() 调用。
    页码转换：pymupdf4llm 返回 0-based page_number，
    本函数将其转为 1-based 存入 PageChunk，方便自然理解。

    Args:
        doc: 已打开的 pymupdf.Document 对象。
        source: 来源标识。
        pages: 页码列表（0-based，直接传给 pymupdf4llm）。
        include_header_footer: 是否包含页眉页脚。

    Returns:
        PDFParseResult。
    """
    ...


def _clean_markdown(text: str) -> str:
    """清理提取的 Markdown 文本。

    处理内容：
    - 合并连续 3+ 空行为 2 个
    - 移除独立成行的纯数字页码残留（如 Layout 未完全过滤的情况）

    Layout 模式下页眉页脚已由 ML 模型自动处理，
    本函数只做轻量级后处理。

    Args:
        text: 原始 Markdown 文本。

    Returns:
        清理后的 Markdown 文本。
    """
    ...
