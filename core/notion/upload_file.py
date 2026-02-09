import asyncio
import logging
from io import BytesIO
from typing import TypedDict

import httpx
import pymupdf

from . import notion

logger = logging.getLogger(__name__)

BATCH_SIZE = 95
COVER_SIZE = 5


class FileUpload(TypedDict):
    url: str
    title: str


class FileUploaded(FileUpload):
    file_id: str
    successed: bool
    error: str | None


async def upload_files_with_local(file_list: list[FileUpload]) -> list[FileUploaded]:
    # 创建上传任务，并等待完成
    upload_tasks = [_upload_internal_and_wait(each) for each in file_list]
    file_uploaded = await asyncio.gather(*upload_tasks)

    # 返回结构
    logger.info(
        f"上传完成，成功: {sum(1 for f in file_list if f.get('successed'))}/{len(file_list)}"
    )
    return file_uploaded


async def upload_files_with_url(file_list: list[FileUpload]) -> list[FileUploaded]:
    """
    异步上传文件列表中的所有文件，并等待上传完成。

    参数:
        file_list (list[FileUpload]): 包含待上传文件信息的列表，每个元素应为 FileUpload 类型。

    返回:
        list[FileUpload]: 上传完成后返回的文件列表，其中每个文件对象可能包含上传状态等信息。
    """

    # 1. 创建所有上传任务
    upload_tasks = [_upload_external_and_wait(each) for each in file_list]

    # 2. 并发等待所有文件上传完成
    file_uploaded = await asyncio.gather(*upload_tasks)

    # 3. 所有文件处理完毕，返回结果
    logger.info(
        f"上传完成: {sum(1 for f in file_uploaded if f['successed'])}/{len(file_uploaded)}个文件已成功"
    )
    return file_uploaded


async def _upload_internal_and_wait(file_info: FileUpload) -> list[FileUploaded]:
    # 下载文件
    logger.info(f"下载文件：{file_info['title']} ({file_info['url']})")
    async with httpx.AsyncClient() as client:
        response = await client.get(file_info["url"])
        response.raise_for_status()

    # 所有传入的文件都已经是分割后的文件，直接上传
    # 创建单个文件上传任务
    result = await notion.file_uploads.create(
        filename=file_info["title"] + ".PDF", content=BytesIO(response.content)
    )
    file_id = result["id"]

    # 轮询等待完成
    poll_result = await _poll_upload_status(file_id)

    # 处理结果
    if poll_result["status"] == "uploaded":
        file_successed = True
        file_error = None
        logger.info(f"✓ {file_info['title']} 上传成功")
    else:
        file_successed = False
        error_msg = poll_result.get("file_import_result", {}).get("error", "未知错误")
        file_error = error_msg
        logger.error(f"✗ {file_info['title']} 上传失败: {error_msg}")

    return [
        FileUploaded(
            **file_info, file_id=file_id, successed=file_successed, error=file_error
        )
    ]


async def _upload_buffer(
    buffer: BytesIO, file_info: FileUpload, part: int
) -> FileUploaded:
    start_page = (BATCH_SIZE - COVER_SIZE) * (part - 1) + 1
    end_page = (BATCH_SIZE - COVER_SIZE) * (part - 1) + BATCH_SIZE
    result = await notion.file_uploads.create(
        filename=f"{file_info['title']}(P{start_page}-P{end_page}).PDF", content=buffer
    )
    return FileUploaded(**file_info, file_id=result["id"], successed=True, error=None)


def _split_pdf(content: bytes) -> list[BytesIO]:
    doc = pymupdf.open(stream=content)
    buffer_list = []
    for i in range(0, doc.page_count, BATCH_SIZE):
        sub_doc = pymupdf.open()
        sub_doc.insert_pdf(doc, from_page=i, to_page=min(i + 94, doc.page_count - 1))

        buffer = BytesIO()
        sub_doc.save(buffer)
        buffer.seek(0)
        buffer_list.append(buffer)
    return buffer_list


async def _upload_external_and_wait(file_info: FileUpload) -> FileUploaded:
    """上传单个文件并轮询直到完成"""
    # 创建上传
    logger.info(f"上传外部文件：{file_info['title']} ({file_info['url']})")
    response = await notion.file_uploads.create(
        mode="external_url",
        filename=file_info["title"] + ".PDF",
        external_url=file_info["url"],
    )
    file_id = response["id"]
    # 轮询等待完成
    result = await _poll_upload_status(file_id)

    # 处理结果
    if result["status"] == "uploaded":
        file_successed = True
        file_error = None
        logger.info(f"✓ {file_info['title']} 上传成功")
    else:
        file_successed = False
        error_msg = result.get("file_import_result", {}).get("error", "未知错误")
        file_error = error_msg
        logger.error(f"✗ {file_info['title']} 上传失败: {error_msg}")
    file_uploaded = FileUploaded(
        **file_info, file_id=file_id, successed=file_successed, error=file_error
    )
    return file_uploaded


async def _poll_upload_status(file_id: str, max_attempts=10):
    """轮询文件状态，指数退避：1, 2, 4, 8..."""
    intervals = [1, 2, 4, 8, 16]

    for attempt in range(max_attempts):
        response = await notion.file_uploads.retrieve(file_id)
        status = response["status"]

        logger.debug(f"文件 {file_id} 状态: {status} (第{attempt + 1}次)")

        # 完成或失败都返回
        if status in ["uploaded", "failed"]:
            return response

        # 未完成，等待后重试
        if attempt < len(intervals):
            wait_time = intervals[attempt]
        else:
            wait_time = intervals[-1]  # 最多等16秒

        await asyncio.sleep(wait_time)

    # 超时
    return {"status": "failed", "file_import_result": {"error": "轮询超时"}}


__all__ = ["upload_files_with_url", "upload_files_with_local"]
