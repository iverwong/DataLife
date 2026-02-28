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
    # 统一转为 Path 对象
    path = Path(pdf_path)

    # 检查文件是否存在
    if not path.exists():
        raise PDFFileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    source = str(path)
    doc: pymupdf.Document | None = None

    try:
        # 必须传 str 给 pymupdf.open，不能传 Path
        doc = pymupdf.open(str(path))

        # 检查加密状态
        if doc.is_encrypted:
            # 尝试空密码认证
            if not doc.authenticate(""):
                raise PDFEncryptedError(f"PDF 文件已加密，无法打开: {pdf_path}")

        # 使用线程池调用同步解析函数
        result = await asyncio.to_thread(
            _parse_document,
            doc,
            source=source,
            pages=pages,
            include_header_footer=include_header_footer,
        )

        return result

    except PDFEncryptedError:
        # 已在上游处理并关闭 doc，这里重新抛出
        raise
    except (RuntimeError, ValueError, OSError) as e:
        # pymupdf 原生异常，检查是否是加密相关
        error_msg = str(e).lower()
        if "encrypt" in error_msg:
            raise PDFEncryptedError(f"PDF 文件已加密，无法解析: {pdf_path}", cause=e) from e
        raise PDFCorruptedError(f"PDF 文件损坏或格式无效: {pdf_path}", cause=e) from e
    except PDFParsingError:
        # 已经是正确的异常类型，直接重新抛出
        raise
    except Exception as e:
        # 其它未知异常，检查是否是加密相关
        error_msg = str(e).lower()
        if "encrypt" in error_msg:
            raise PDFEncryptedError(f"PDF 文件已加密，无法解析: {pdf_path}", cause=e) from e
        raise PDFParsingError(f"PDF 解析失败: {pdf_path}", cause=e) from e
    finally:
        # 确保文档被关闭
        if doc is not None:
            doc.close()


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
    # 检查字节内容是否为空
    if not pdf_bytes:
        raise PDFCorruptedError("PDF 内容为空")

    doc: pymupdf.Document | None = None

    try:
        # 从字节流创建 Document
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

        # 检查加密状态
        if doc.is_encrypted:
            # 尝试空密码认证
            if not doc.authenticate(""):
                raise PDFEncryptedError(f"PDF 已加密: {source}")

        # 使用线程池调用同步解析函数
        result = await asyncio.to_thread(
            _parse_document,
            doc,
            source=source,
            pages=pages,
            include_header_footer=include_header_footer,
        )

        return result

    except PDFEncryptedError:
        # 已在上游处理并关闭 doc，这里重新抛出
        raise
    except (RuntimeError, ValueError, OSError) as e:
        # pymupdf 原生异常，检查是否是加密相关
        error_msg = str(e).lower()
        if "encrypt" in error_msg:
            raise PDFEncryptedError(f"PDF 已加密，无法解析: {source}", cause=e) from e
        raise PDFCorruptedError(f"PDF 内容无效或格式损坏: {source}", cause=e) from e
    except PDFParsingError:
        # 已经是正确的异常类型，直接重新抛出
        raise
    except Exception as e:
        # 其它未知异常，检查是否是加密相关
        error_msg = str(e).lower()
        if "encrypt" in error_msg:
            raise PDFEncryptedError(f"PDF 已加密，无法解析: {source}", cause=e) from e
        raise PDFParsingError(f"PDF 解析失败: {source}", cause=e) from e
    finally:
        # 确保文档被关闭
        if doc is not None:
            doc.close()


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
    logfire.info("Starting PDF parsing", source=source, page_count=doc.page_count)

    # 调用 pymupdf4llm 进行解析
    # pymupdf4llm.to_markdown 返回 str | list[dict]，page_chunks=True 时返回 list[dict]
    chunks_raw: list[dict] = pymupdf4llm.to_markdown(  # type: ignore[assignment]
        doc,
        pages=pages,
        page_chunks=True,
        header=include_header_footer,
        footer=include_header_footer,
        force_text=True,
        show_progress=False,
    )

    chunks: list[PageChunk] = []
    for chunk_dict in chunks_raw:
        # pymupdf4llm 返回的 page_number 是 0-based，转换为 1-based
        # pymupdf4llm 返回的 page_number 已经是 1-based
        page_number = chunk_dict.get("metadata", {}).get("page_number", 1)

        # 提取 markdown 文本并清理
        raw_text = chunk_dict.get("text", "")
        cleaned_text = _clean_markdown(raw_text)

        # 构建 PageChunk
        chunk = PageChunk(
            page_number=page_number,
            markdown_text=cleaned_text,
            metadata=chunk_dict.get("metadata", {}),
            toc_items=chunk_dict.get("toc_items", []),
            page_boxes=chunk_dict.get("page_boxes", []),
        )
        chunks.append(chunk)

        logfire.debug(
            "Page parsed",
            source=source,
            page=page_number,
            text_length=len(cleaned_text),
        )

    result = PDFParseResult(
        source=source,
        page_count=doc.page_count,
        chunks=chunks,
    )

    logfire.info(
        "PDF parsing completed",
        source=source,
        total_pages=len(chunks),
    )

    return result


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
    import re

    # 合并连续 3+ 空行为 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 移除独立成行的纯数字页码残留（如 "1", "2", "12" 等）
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

    return text.strip()
