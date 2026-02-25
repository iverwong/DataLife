"""PDF 文件下载与分割工具。

将大型 PDF 公告文件按固定页数分割为多个小文件，
相邻分块之间保留重叠页以保证内容连贯性。
"""

from io import BytesIO
from typing import cast

import httpx
import pymupdf  # pyright: ignore[reportMissingTypeStubs]
from loguru import logger

from core.models.announcement import AnnouncementWithHash

from .announcement import AnnouncementWithContent

CHUNK_SIZE = 20
"""每个分割块的最大页数。"""

REP_SIZE = 2
"""相邻分割块之间的重叠页数。"""


async def split_pdf(
    announcement_list: list[AnnouncementWithHash],
) -> list[tuple[AnnouncementWithContent, AnnouncementWithHash]]:
    """下载并分割公告列表中的 PDF 文件。

    页数不超过 CHUNK_SIZE 的 PDF 作为整体保留；超过的按 CHUNK_SIZE 分割，
    相邻块之间重叠 REP_SIZE 页。分割失败时保留原始公告（空内容）。

    Args:
        announcement_list: 需要分割的公告及其哈希值列表。

    Returns:
        分割后的公告内容与原始哈希信息的配对列表。每个元素包含
        带二进制内容的公告对象和对应的原始 AnnouncementWithHash。
    """
    result: list[tuple[AnnouncementWithContent, AnnouncementWithHash]] = []
    task_logger = logger.bind(count=len(announcement_list))

    for item in announcement_list:
        ann = item.announcement
        subtask_logger = task_logger.bind(title=ann.title)
        subtask_logger.info("开始分割PDF: {}", ann.title)

        try:
            pdf_content = await _download_pdf(ann.url)
            page_count = _get_pdf_page_count(pdf_content)
            subtask_logger.info("PDF页数: {}", page_count)

            if page_count <= CHUNK_SIZE:
                new_announcement = AnnouncementWithContent(
                    id=ann.id,
                    stock=ann.stock,
                    title=ann.title,
                    size=ann.size,
                    url=ann.url,
                    published_date=ann.published_date,
                    content=pdf_content,
                )
                subtask_logger.success("PDF处理完成（无需分割）: {}", ann.title)
                result.append((new_announcement, item))
            else:
                split_contents = _split_pdf_content(pdf_content)
                subtask_logger.success("PDF分割完成: {}，共{}块", ann.title, len(split_contents))

                for i, content in enumerate(split_contents):
                    start_page = i * (CHUNK_SIZE - REP_SIZE) + 1
                    end_page = min(start_page + CHUNK_SIZE - 1, page_count)

                    new_title = f"{ann.title}(P{start_page}-P{end_page})"
                    new_announcement = AnnouncementWithContent(
                        id=ann.id,
                        stock=ann.stock,
                        title=new_title,
                        size=len(content) // 1024,
                        url=ann.url,
                        published_date=ann.published_date,
                        content=content,
                    )
                    result.append((new_announcement, item))

        except Exception:
            subtask_logger.exception("分割PDF失败 {}", ann.title)
            # 分割失败时保留原始公告（空内容），仍关联原始哈希
            fallback = AnnouncementWithContent(
                id=ann.id,
                stock=ann.stock,
                title=ann.title,
                size=ann.size,
                url=ann.url,
                published_date=ann.published_date,
                content=b"",
            )
            result.append((fallback, item))

    return result


async def _download_pdf(url: str) -> bytes:
    """异步下载 PDF 文件内容。

    Args:
        url: PDF 文件的下载地址。

    Returns:
        PDF 文件的二进制内容。

    Raises:
        httpx.HTTPStatusError: HTTP 请求返回非 2xx 状态码。
        httpx.TimeoutException: 请求超时。
    """
    task_logger = logger.bind(url=url)
    task_logger.info("开始下载PDF文件: {}", url)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        task_logger.success("下载PDF文件成功: {}", url)
        return response.content


def _get_pdf_page_count(content: bytes) -> int:
    """获取 PDF 文件的总页数。

    Args:
        content: PDF 文件的二进制内容。

    Returns:
        PDF 的总页数。
    """
    doc = pymupdf.open(stream=content)
    page_count: int = cast(int, doc.page_count)
    doc.close()
    return page_count


def _split_pdf_content(content: bytes) -> list[bytes]:
    """将 PDF 内容按固定页数分割为多个部分。

    相邻分块之间保留 REP_SIZE 页的重叠，以保证内容连贯性。

    Args:
        content: PDF 文件的二进制内容。

    Returns:
        分割后的 PDF 二进制内容列表。
    """
    doc = pymupdf.open(stream=content)
    chunks: list[bytes] = []

    page_count: int = cast(int, doc.page_count)
    for i in range(0, page_count, CHUNK_SIZE - REP_SIZE):
        new_doc = pymupdf.open()

        start_page = i
        end_page = min(i + CHUNK_SIZE - 1, page_count - 1)

        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)  # pyright: ignore[reportUnknownMemberType]

        buffer = BytesIO()
        new_doc.save(buffer)  # pyright: ignore[reportUnknownMemberType]
        _ = buffer.seek(0)

        chunks.append(buffer.getvalue())
        new_doc.close()

    doc.close()
    return chunks
