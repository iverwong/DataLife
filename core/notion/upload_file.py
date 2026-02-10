import asyncio
import functools
import logging
from io import BytesIO
from typing import ParamSpec, TypedDict, TypeVar

import httpx
import pymupdf

from . import notion

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0  # 基础延迟秒数
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ReadError,
    httpx.WriteError,
)

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


def _with_retry(
    max_retries: int = MAX_RETRIES, retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS
):
    """装饰器：为异步函数添加指数退避重试逻辑

    Args:
        max_retries: 最大重试次数
        retryable_exceptions: 需要重试的异常类型元组
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                        logger.info(
                            f"[重试] {func.__name__} 第 {attempt}/{max_retries} 次尝试，等待 {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    logger.warning(
                        f"[重试] {func.__name__} 遇到网络错误: {type(e).__name__}: {e}"
                    )
                    if attempt >= max_retries:
                        logger.error(
                            f"[重试] {func.__name__} 已达到最大重试次数 ({max_retries})，放弃重试"
                        )
                        raise
                except Exception as e:
                    logger.error(
                        f"[重试] {func.__name__} 遇到非重试错误: {type(e).__name__}: {e}"
                    )
                    raise
            raise last_exception

        return wrapper

    return decorator


@_with_retry()
async def _upload_internal_and_wait(file_info: FileUpload) -> list[FileUploaded]:
    # 下载文件
    logger.info(f"下载文件：{file_info['title']} ({file_info['url']})")
    async with httpx.AsyncClient() as client:
        response = await client.get(file_info["url"])
        response.raise_for_status()
    logger.info(f"下载完成：{file_info['title']} ({len(response.content)} 字节)")

    # 所有传入的文件都已经是分割后的文件，直接上传
    # 创建单个文件上传任务
    logger.info(f"开始上传文件到 Notion：{file_info['title']}")
    result = await notion.file_uploads.create(
        filename=file_info["title"] + ".PDF", content=BytesIO(response.content)
    )
    file_id = result["id"]
    logger.info(f"文件创建成功，file_id={file_id}，开始轮询状态...")

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


@_with_retry()
async def _upload_external_and_wait(file_info: FileUpload) -> FileUploaded:
    """上传单个文件并轮询直到完成"""
    # 创建上传
    logger.info(f"上传外部文件：{file_info['title']} ({file_info['url']})")
    logger.info("调用 Notion API: file_uploads.create (external_url 模式)")
    response = await notion.file_uploads.create(
        mode="external_url",
        filename=file_info["title"] + ".PDF",
        external_url=file_info["url"],
    )
    file_id = response["id"]
    logger.info(f"外部文件创建成功，file_id={file_id}，开始轮询状态...")

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


@_with_retry()
async def _poll_upload_status(file_id: str, max_attempts=10):
    """轮询文件状态，指数退避：1, 2, 4, 8...

    每次查询 Notion API 失败时会自动重试（最多3次）
    """
    intervals = [1, 2, 4, 8, 16]

    for attempt in range(max_attempts):
        logger.info(
            f"轮询文件状态: file_id={file_id} (第 {attempt + 1}/{max_attempts} 次)"
        )
        response = await notion.file_uploads.retrieve(file_id)
        status = response["status"]

        logger.info(f"文件 {file_id} 状态: {status}")

        # 完成或失败都返回
        if status in ["uploaded", "failed"]:
            logger.info(f"文件 {file_id} 处理结束，最终状态: {status}")
            return response

        # 未完成，等待后重试
        if attempt < len(intervals):
            wait_time = intervals[attempt]
        else:
            wait_time = intervals[-1]  # 最多等16秒

        logger.info(f"文件 {file_id} 未完成，等待 {wait_time} 秒后再次查询...")
        await asyncio.sleep(wait_time)

    # 超时
    logger.warning(f"文件 {file_id} 轮询超时 (超过 {max_attempts} 次尝试)")
    return {"status": "failed", "file_import_result": {"error": "轮询超时"}}


__all__ = ["upload_files_with_url", "upload_files_with_local"]
