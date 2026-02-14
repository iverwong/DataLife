import asyncio
from datetime import datetime
from typing import TypedDict

from operator import attrgetter

from loguru import logger

from .client import notion
from .models import FileImportError, FileUploadResponse
from .retry_helper import with_retry


class FileUpload(TypedDict):
    stock: str
    url: str
    title: str
    published_date: datetime
    hash_content: str  # 新增：携带原始hash内容


class FileUploadWithContent(FileUpload):
    content: bytes


class FileUploaded(FileUpload):
    file_id: str
    successed: bool
    error: str | None


async def upload_files_with_local(
    file_list: list[FileUploadWithContent],
    max_retries: int = 3,
) -> list[FileUploaded]:
    """上传本地文件，对失败的文件自动重试。

    Args:
        file_list: 待上传的文件列表
        max_retries: 失败文件的最大重试次数，默认 3 次

    Returns:
        上传结果列表
    """
    all_results: list[FileUploaded] = []
    pending_files = file_list  # 待处理的文件列表
    attempt = 0

    while pending_files and attempt <= max_retries:
        logger.info(f"开始处理 {len(pending_files)} 个文件")

        if attempt > 0:
            logger.warning(
                f"[重试] 第 {attempt}/{max_retries} 次重试，待重试文件: {[f['title'] for f in pending_files]}"
            )

        # 创建上传任务，并等待完成
        upload_tasks = [_upload_internal_and_wait(each) for each in pending_files]
        batch_results = await asyncio.gather(*upload_tasks)

        # 扁平化列表（每个任务返回 list[FileUploaded]，需要展开）
        flattened = [item for sublist in batch_results for item in sublist]

        # 分离成功和失败的结果
        succeeded = [r for r in flattened if r["successed"]]
        failed = [r for r in flattened if not r["successed"]]
        logger.info(f"本轮完成: 成功 {len(succeeded)} 个, 失败 {len(failed)} 个")

        # 成功的立即加入最终结果
        all_results.extend(succeeded)

        # 处理失败的文件
        if attempt < max_retries:
            # 还有重试机会，准备重试
            failed_urls = {r["url"] for r in failed}
            pending_files = [f for f in file_list if f["url"] in failed_urls]
        else:
            # 已达最大重试次数，失败的也加入最终结果
            logger.error(
                f"以下文件已达最大重试次数仍失败: {[f['title'] for f in failed]}"
            )
            all_results.extend(failed)
            pending_files = []

        attempt += 1

    # 返回结构
    logger.info(
        f"上传完成，成功: {sum(1 for f in all_results if f.get('successed'))}/{len(all_results)}"
    )
    return all_results


@with_retry()
async def _upload_internal_and_wait(
    file_info: FileUploadWithContent,
) -> list[FileUploaded]:
    task_logger = logger.bind(file=file_info["title"])

    # 所有传入的文件都已经是分割后的文件，直接上传
    # 创建单个文件上传任务
    task_logger.info(f"创建{file_info['title']}的Notion上传对象")
    create_result = FileUploadResponse.model_validate(
        await notion.file_uploads.create(
            filename=file_info["title"] + ".PDF", content_type="application/pdf"
        )
    )
    file_id = create_result.id
    task_logger.info(
        f"文件创建成功，{file_info['title']}|{file_id}，开始上传", file_id=file_id
    )

    # 开始上传
    send_result = FileUploadResponse.model_validate(
        await notion.file_uploads.send(
            file_id,
            file=(file_info["title"] + ".PDF", file_info["content"], "application/pdf"),
        )
    )

    if send_result.status == "uploaded":
        file_successed = True
        file_error = None
        task_logger.success(f"上传文件 {file_info['title']} 成功")
    else:
        file_successed = False
        file_error = (
            attrgetter("file_import_result.error.message")(send_result) or "未知错误"
        )
        task_logger.error(f"上传文件 {file_info['title']} 失败，响应为{send_result}")

    return [
        FileUploaded(
            stock=file_info["stock"],
            url=file_info["url"],
            title=file_info["title"],
            published_date=file_info["published_date"],
            hash_content=file_info["hash_content"],
            file_id=file_id,
            successed=file_successed,
            error=file_error,
        )
    ]


async def upload_files_with_url(
    file_list: list[FileUpload],
    max_retries: int = 2,
) -> list[FileUploaded]:
    """异步上传文件列表中的所有文件，对失败的文件自动重试。

    Args:
        file_list: 包含待上传文件信息的列表，每个元素应为 FileUpload 类型。
        max_retries: 失败文件的最大重试次数，默认 2 次。

    Returns:
        上传完成后返回的文件列表，其中每个文件对象包含上传状态等信息。
    """
    task_logger = logger.bind(file_list=file_list)
    task_logger.info("开始上传文件列表中的所有文件")

    all_results: list[FileUploaded] = []
    pending_files = file_list  # 待处理的文件列表
    attempt = 0

    while pending_files and attempt <= max_retries:
        task_logger.info(f"开始处理 {len(pending_files)} 个文件")

        if attempt > 0:
            task_logger.warning(
                f"[重试] 第 {attempt}/{max_retries} 次重试，待重试文件: {[f['title'] for f in pending_files]}"
            )

        # 1. 创建所有上传任务
        upload_tasks = [_upload_external_and_wait(each) for each in pending_files]

        # 2. 并发等待所有文件上传完成
        batch_results = await asyncio.gather(*upload_tasks)

        # 3. 分离成功和失败的结果
        succeeded = [r for r in batch_results if r["successed"]]
        failed = [r for r in batch_results if not r["successed"]]
        task_logger.info(f"本轮完成: 成功 {len(succeeded)} 个, 失败 {len(failed)} 个")

        # 4. 成功的立即加入最终结果
        all_results.extend(succeeded)

        # 5. 处理失败的文件
        if attempt < max_retries:
            # 还有重试机会，准备重试
            failed_urls = {r["url"] for r in failed}
            pending_files = [f for f in file_list if f["url"] in failed_urls]
        else:
            # 已达最大重试次数，失败的也加入最终结果
            task_logger.error(
                f"以下文件已达最大重试次数仍失败: {[f['title'] for f in failed]}"
            )
            all_results.extend(failed)
            pending_files = []

        attempt += 1

    # 6. 所有文件处理完毕，返回结果
    task_logger.success(
        f"上传任务完成: {sum(1 for f in all_results if f['successed'])}/{len(all_results)}个文件已成功",
        file_uploaded=all_results,
    )
    return all_results


@with_retry()
async def _upload_external_and_wait(file_info: FileUpload) -> FileUploaded:
    """上传单个文件并轮询直到完成"""
    task_logger = logger.bind(file_info=file_info)
    # 创建上传
    task_logger.info("上传外部文件：{} ({})", file_info["title"], file_info["url"])
    create_response = FileUploadResponse.model_validate(
        await notion.file_uploads.create(
            mode="external_url",
            filename=file_info["title"] + ".PDF",
            external_url=file_info["url"],
        )
    )
    file_id = create_response.id
    task_logger.info("外部文件创建成功，id={}，开始轮询", file_id)

    # 轮询直到完成
    poll_result = await _poll_upload_status(file_id, file_info["title"])

    # 返回结果
    if poll_result.status == "uploaded":
        task_logger.success(f"✓ {file_info['title']} 上传成功")
        return FileUploaded(**file_info, file_id=file_id, successed=True, error=None)
    else:
        file_import_result = poll_result.file_import_result
        if file_import_result:
            if isinstance(file_import_result, FileImportError):
                error_msg = file_import_result.error.message
            else:
                task_logger.error(
                    f"收到了状态不为 `uploaded` 但文件导入结果不为 `error` 的报文：{poll_result}"
                )
                raise TypeError(
                    "收到了状态不为 `uploaded` 但文件导入结果不为 `error` 的报文"
                )
        else:
            error_msg = "轮询超时"
        task_logger.error(f"✗ {file_info['title']} 上传失败: {error_msg}")
        return FileUploaded(
            **file_info,
            file_id=file_id,
            successed=False,
            error=error_msg,
        )


@with_retry()
async def _poll_upload_status(
    file_id: str, filename: str, max_attempts: int = 5
) -> FileUploadResponse:
    """轮询文件状态，指数退避：1, 2, 4, 8...

    每次查询 Notion API 失败时会自动重试（最多3次）

    Args:
        file_id: Notion 文件上传任务 ID
        filename: 原始文件名（用于日志排查）
        max_attempts: 最大轮询次数
    """
    task_logger = logger.bind(file_id=file_id, filename=filename)
    intervals = [1, 2, 4, 8, 16]

    for attempt in range(max_attempts):
        task_logger.info(
            f"轮询文件状态: {filename} | file_id={file_id} (第 {attempt + 1}/{max_attempts} 次)"
        )
        response = FileUploadResponse.model_validate(
            await notion.file_uploads.retrieve(file_id)
        )

        task_logger.info(f"文件 {filename} | file_id={file_id} 状态: {response.status}")

        # 完成或失败都返回
        if response.status in ("uploaded", "failed"):
            task_logger.info(
                f"文件 {filename} | file_id={file_id} 处理结束，最终状态: {response.status}"
            )
            return response

        # 未完成，等待后重试
        if attempt < len(intervals):
            wait_time = intervals[attempt]
        else:
            wait_time = intervals[-1]  # 最多等16秒

        task_logger.info(
            f"文件 {filename} 未完成上传，等待 {wait_time} 秒后再次查询..."
        )
        await asyncio.sleep(wait_time)

    # 超时
    task_logger.warning(
        f"文件 {filename} | file_id={file_id} 轮询超时 (超过 {max_attempts} 次尝试)"
    )
    return FileUploadResponse(
        id=file_id,
        created_time="",
        status="failed",
    )


__all__ = ["upload_files_with_url", "upload_files_with_local"]
