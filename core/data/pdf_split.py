from io import BytesIO

import httpx
import pymupdf  # pyright: ignore[reportMissingTypeStubs]
from loguru import logger
from typing import cast
from .announcement import Announcement, AnnouncementWithContent

CHUNK_SIZE = 95
REP_SIZE = 5


def split_pdf(
    announcement_list: list[tuple[Announcement, str]],
) -> list[tuple[AnnouncementWithContent, str]]:
    """
    将公告列表中的PDF文件进行分割处理。

    参数:
        announcement_list (list[Announcement]): 需要分割的公告列表

    返回:
        list[Announcement]: 分割后的公告列表，包含原始公告和新生成的分割公告
    """
    result: list[tuple[AnnouncementWithContent, str]] = []
    task_logger = logger.bind(announcement_list=announcement_list)

    for announcement in announcement_list:
        subtask_logger = task_logger.bind(announcement=announcement)
        subtask_logger.info(f"开始分割PDF: {announcement[0].title}")

        try:
            # 下载PDF文件
            pdf_content = _download_pdf(announcement[0].url)
            page_count = _get_pdf_page_count(pdf_content)
            subtask_logger.info(f"PDF页数: {page_count}")

            # 如果页数较少，作为一个整体处理
            if page_count <= CHUNK_SIZE:
                # 直接创建一个公告对象，添加页码信息
                new_title = f"{announcement[0].title}(P1-P{page_count})"
                new_announcement = (
                    AnnouncementWithContent(
                        id=announcement[0].id,  # 保持原始ID不变
                        stock=announcement[0].stock,
                        title=new_title,
                        size=announcement[0].size,  # 保持原始大小
                        url=announcement[0].url,
                        published_date=announcement[0].published_date,
                        content=pdf_content,
                    ),
                    announcement[1],
                )
                subtask_logger.success(f"PDF分割完成: {announcement[0].title}")
                result.append(new_announcement)
            else:
                # 分割PDF
                subtask_logger.info(f"开始分割PDF: {announcement[0].title}")
                split_contents = _split_pdf_content(pdf_content)
                subtask_logger.success(f"PDF分割完成: {announcement[0].title}")

                # 为每个分割部分创建新的公告对象
                for i, content in enumerate(split_contents):
                    start_page = i * (CHUNK_SIZE - REP_SIZE) + 1
                    end_page = min(start_page + CHUNK_SIZE - 1, page_count)

                    new_title = f"{announcement[0].title}(P{start_page}-P{end_page})"
                    new_announcement = (
                        AnnouncementWithContent(
                            id=announcement[0].id,  # 保持原始ID不变
                            stock=announcement[0].stock,
                            title=new_title,
                            size=len(content) // 1024,  # 估算大小(KB)
                            url=announcement[0].url,
                            published_date=announcement[0].published_date,
                            content=content,
                        ),
                        announcement[1],
                    )
                    subtask_logger.success(f"PDF分割完成: {announcement[0].title}")
                    result.append(new_announcement)

        except Exception:
            subtask_logger.exception(f"分割PDF失败 {announcement[0].title}")
            # 分割失败时保留原始公告（包装为带空内容的 AnnouncementWithContent）
            result.append(
                (
                    AnnouncementWithContent(
                        id=announcement[0].id,
                        stock=announcement[0].stock,
                        title=announcement[0].title,
                        size=announcement[0].size,
                        url=announcement[0].url,
                        published_date=announcement[0].published_date,
                        content=b"",
                    ),
                    announcement[1],
                )
            )

    return result


def _download_pdf(url: str) -> bytes:
    """下载PDF文件内容"""
    task_logger = logger.bind(url=url)
    task_logger.info(f"开始下载PDF文件: {url}")
    with httpx.Client() as client:
        response = client.get(url)
        try:
            _ = response.raise_for_status()
        except httpx.HTTPStatusError:
            task_logger.exception(f"下载PDF文件失败: {url}")
            raise
        task_logger.success(f"下载PDF文件成功: {url}", response=response)
        return response.content


def _get_pdf_page_count(content: bytes) -> int:
    """获取PDF页数"""
    doc = pymupdf.open(stream=content)
    page_count: int = cast(int, doc.page_count)
    doc.close()
    return page_count


def _split_pdf_content(content: bytes) -> list[bytes]:
    """
    分割PDF内容为多个部分

    参数:
        content (bytes): PDF文件的二进制内容

    返回:
        list[bytes]: 分割后的PDF内容列表
    """
    doc = pymupdf.open(stream=content)
    chunks: list[bytes] = []

    page_count: int = cast(int, doc.page_count)
    for i in range(0, page_count, CHUNK_SIZE - REP_SIZE):
        # 创建新的PDF文档
        new_doc = pymupdf.open()

        # 计算要复制的页码范围
        start_page = i
        end_page = min(i + CHUNK_SIZE - 1, page_count - 1)

        # 复制页面到新文档
        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)  # pyright: ignore[reportUnknownMemberType]

        # 保存到内存缓冲区
        buffer = BytesIO()
        new_doc.save(buffer)  # pyright: ignore[reportUnknownMemberType]
        _ = buffer.seek(0)

        chunks.append(buffer.getvalue())

        # 清理资源
        new_doc.close()

    doc.close()
    return chunks
