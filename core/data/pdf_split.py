"""PDF 文件下载与分割工具。

将大型 PDF 公告文件按固定页数分割为多个小文件，
相邻分块之间保留重叠页以保证内容连贯性。
"""

from io import BytesIO
from typing import cast

import httpx
import pymupdf
from loguru import logger

from core.models.announcement import AnnouncementWithHash
from core.utils import gather_with_concurrency, get_pdf_download_semaphore

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

    使用并发控制限制同时下载的 PDF 数量，防止资源耗尽。

    Args:
        announcement_list: 需要分割的公告及其哈希值列表。

    Returns:
        分割后的公告内容与原始哈希信息的配对列表。每个元素包含
        带二进制内容的公告对象和对应的原始 AnnouncementWithHash。
    """
    if not announcement_list:
        return []

    logger.info("开始并发处理 {} 个 PDF 文件", len(announcement_list))

    # 构建协程列表
    tasks = [_process_single_pdf(item) for item in announcement_list]

    # 使用并发限制执行所有任务
    results = await gather_with_concurrency(get_pdf_download_semaphore(), tasks)

    # 展平结果（每个任务可能返回多个分割块）
    flattened: list[tuple[AnnouncementWithContent, AnnouncementWithHash]] = []
    for item_results in results:
        flattened.extend(item_results)

    logger.success("PDF 处理完成，共生成 {} 个文件块", len(flattened))
    return flattened


async def _process_single_pdf(
    item: AnnouncementWithHash,
) -> list[tuple[AnnouncementWithContent, AnnouncementWithHash]]:
    """处理单个 PDF 文件：下载、判断是否分割、返回结果。

    Args:
        item: 包含公告信息和哈希值的对象。

    Returns:
        该 PDF 对应的公告内容列表（可能是单个或多个分割块）。
    """
    ann = item.announcement
    result: list[tuple[AnnouncementWithContent, AnnouncementWithHash]] = []

    try:
        pdf_content = await _download_pdf(ann.url)
        page_count = _get_pdf_page_count(pdf_content)

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
            logger.debug("PDF 无需分割: {} ({} 页)", ann.title, page_count)
            result.append((new_announcement, item))
        else:
            split_contents = _split_pdf_content(pdf_content)
            logger.info(
                "PDF 分割完成: {} ({} 页 -> {} 块)",
                ann.title,
                page_count,
                len(split_contents),
            )

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
        logger.exception("PDF 分割失败: {}", ann.title)
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
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        logger.debug("PDF 下载完成: {}", url)
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
