from io import BytesIO

import httpx
import pymupdf
from loguru import logger

from .announcement import Announcement, AnnouncementWithContent

CHUNK_SIZE = 95
REP_SIZE = 5


def split_pdf(announcement_list: list[Announcement]) -> list[AnnouncementWithContent]:
    """
    将公告列表中的PDF文件进行分割处理。

    参数:
        announcement_list (list[Announcement]): 需要分割的公告列表

    返回:
        list[Announcement]: 分割后的公告列表，包含原始公告和新生成的分割公告
    """
    result: list[AnnouncementWithContent] = []
    task_logger = logger.bind(announcement_list=announcement_list)

    for announcement in announcement_list:
        subtask_logger = task_logger.bind(announcement=announcement)
        subtask_logger.info(f"开始分割PDF: {announcement.title}")

        try:
            # 下载PDF文件
            pdf_content = _download_pdf(announcement.url)
            page_count = _get_pdf_page_count(pdf_content)
            subtask_logger.info(f"PDF页数: {page_count}")

            # 如果页数较少，作为一个整体处理
            if page_count <= CHUNK_SIZE:
                # 直接创建一个公告对象，添加页码信息
                new_title = f"{announcement.title}(P1-P{page_count})"
                new_announcement = AnnouncementWithContent(
                    id=f"{announcement.id}_part1",
                    stock=announcement.stock,
                    title=new_title,
                    size=announcement.size,  # 保持原始大小
                    url=announcement.url,
                    published_date=announcement.published_date,
                    content=pdf_content,
                )
                subtask_logger.success(f"PDF分割完成: {announcement.title}")
                result.append(new_announcement)
            else:
                # 分割PDF
                subtask_logger.info(f"开始分割PDF: {announcement.title}")
                split_contents = _split_pdf_content(pdf_content)
                subtask_logger.success(f"PDF分割完成: {announcement.title}")

                # 为每个分割部分创建新的公告对象
                for i, content in enumerate(split_contents):
                    start_page = i * (CHUNK_SIZE - REP_SIZE) + 1
                    end_page = min(start_page + CHUNK_SIZE - 1, page_count)

                    new_title = f"{announcement.title}(P{start_page}-P{end_page})"
                    new_announcement = AnnouncementWithContent(
                        id=f"{announcement.id}_part{i + 1}",
                        stock=announcement.stock,
                        title=new_title,
                        size=len(content) // 1024,  # 估算大小(KB)
                        url=announcement.url,
                        published_date=announcement.published_date,
                        content=content,
                    )
                    subtask_logger.success(f"PDF分割完成: {announcement.title}")
                    result.append(new_announcement)

        except Exception:
            subtask_logger.exception(f"分割PDF失败 {announcement.title}")
            # 分割失败时保留原始公告
            result.append(announcement)

    return result


def _download_pdf(url: str) -> bytes:
    """下载PDF文件内容"""
    task_logger = logger.bind(url=url)
    task_logger.info(f"开始下载PDF文件: {url}")
    with httpx.Client() as client:
        response = client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            task_logger.exception(f"下载PDF文件失败: {url}")
            raise
        task_logger.success(f"下载PDF文件成功: {url}", response=response)
        return response.content


def _get_pdf_page_count(content: bytes) -> int:
    """获取PDF页数"""
    doc = pymupdf.open(stream=content)
    page_count = doc.page_count
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
    chunks = []

    for i in range(0, doc.page_count, CHUNK_SIZE - REP_SIZE):
        # 创建新的PDF文档
        new_doc = pymupdf.open()

        # 计算要复制的页码范围
        start_page = i
        end_page = min(i + CHUNK_SIZE - 1, doc.page_count - 1)

        # 复制页面到新文档
        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)

        # 保存到内存缓冲区
        buffer = BytesIO()
        new_doc.save(buffer)
        buffer.seek(0)

        chunks.append(buffer.getvalue())

        # 清理资源
        new_doc.close()

    doc.close()
    return chunks
