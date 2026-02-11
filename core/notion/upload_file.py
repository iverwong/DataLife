import asyncio
from typing import TypedDict

from loguru import logger

from . import notion
from .retry_helper import with_retry


class FileUpload(TypedDict):
    url: str
    title: str


class FileUploadWithContent(FileUpload):
    content: bytes


class FileUploaded(FileUpload):
    file_id: str
    successed: bool
    error: str | None


async def upload_files_with_local(
    file_list: list[FileUploadWithContent],
) -> list[FileUploaded]:
    # 创建上传任务，并等待完成
    upload_tasks = [_upload_internal_and_wait(each) for each in file_list]
    file_uploaded = await asyncio.gather(*upload_tasks)

    # 扁平化列表（每个任务返回 list[FileUploaded]，需要展开）
    flattened = [item for sublist in file_uploaded for item in sublist]

    # 返回结构
    logger.info(
        f"上传完成，成功: {sum(1 for f in flattened if f.get('successed'))}/{len(flattened)}"
    )
    return flattened


@with_retry()
async def _upload_internal_and_wait(
    file_info: FileUploadWithContent,
) -> list[FileUploaded]:
    task_logger = logger.bind(file=file_info["title"])

    # 所有传入的文件都已经是分割后的文件，直接上传
    # 创建单个文件上传任务
    task_logger.info(f"创建{file_info['title']}的Notion上传对象")
    create_result = await notion.file_uploads.create(
        filename=file_info["title"] + ".PDF", content_type="application/pdf"
    )
    file_id = create_result["id"]
    task_logger.info(
        f"文件创建成功，{file_info['title']}|{file_id}，开始上传", file_id=file_id
    )

    # 开始上传
    send_result = await notion.file_uploads.send(
        file_id,
        file=(file_info["title"] + ".PDF", file_info["content"], "application/pdf"),
    )

    if send_result["status"] == "uploaded":
        file_successed = True
        file_error = None
        task_logger.success(f"上传文件 {file_info['title']} 成功")
    else:
        file_successed = False
        file_error = send_result.get("file_import_result", {}).get("error", "未知错误")
        task_logger.error(f"上传文件 {file_info['title']} 失败，响应为{send_result}")

    return [
        FileUploaded(
            **file_info, file_id=file_id, successed=file_successed, error=file_error
        )
    ]


async def upload_files_with_url(file_list: list[FileUpload]) -> list[FileUploaded]:
    """
    异步上传文件列表中的所有文件，并等待上传完成。

    参数:
        file_list (list[FileUpload]): 包含待上传文件信息的列表，每个元素应为 FileUpload 类型。

    返回:
        list[FileUpload]: 上传完成后返回的文件列表，其中每个文件对象可能包含上传状态等信息。
    """
    task_logger = logger.bind(file_list=file_list)
    task_logger.info("开始上传文件列表中的所有文件")
    # 1. 创建所有上传任务
    upload_tasks = [_upload_external_and_wait(each) for each in file_list]

    # 2. 并发等待所有文件上传完成
    file_uploaded = await asyncio.gather(*upload_tasks)

    # 3. 所有文件处理完毕，返回结果
    task_logger.success(
        f"上传任务完成: {sum(1 for f in file_uploaded if f['successed'])}/{len(file_uploaded)}个文件已成功",
        file_uploaded=file_uploaded,
    )
    return file_uploaded


@with_retry()
async def _upload_external_and_wait(file_info: FileUpload) -> FileUploaded:
    """上传单个文件并轮询直到完成"""
    task_logger = logger.bind(file_info=file_info)
    # 创建上传
    task_logger.info("上传外部文件：{} ({})", file_info["title"], file_info["url"])
    response = await notion.file_uploads.create(
        mode="external_url",
        filename=file_info["title"] + ".PDF",
        external_url=file_info["url"],
    )
    file_id = response["id"]
    task_logger.info("外部文件创建成功，id={}，开始轮询", file_id, response=response)

    # 轮询直到完成
    poll_result = await _poll_upload_status(file_id, file_info["title"])

    # 返回结果
    if poll_result["status"] == "uploaded":
        task_logger.success(f"✓ {file_info['title']} 上传成功")
        return FileUploaded(**file_info, file_id=file_id, successed=True, error=None)
    else:
        error_msg = poll_result.get("file_import_result", {}).get("error", "未知错误")
        task_logger.error(f"✗ {file_info['title']} 上传失败: {error_msg}")
        return FileUploaded(
            **file_info, file_id=file_id, successed=False, error=error_msg
        )


@with_retry()
async def _poll_upload_status(file_id: str, filename: str, max_attempts=10):
    """轮询文件状态，指数退避：1, 2, 4, 8...

    每次查询 Notion API 失败时会自动重试（最多3次）

    参数:
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
        response = await notion.file_uploads.retrieve(file_id)
        status = response["status"]

        task_logger.info(
            f"文件 {filename} | file_id={file_id} 状态: {status}", response=response
        )

        # 完成或失败都返回
        if status in ["uploaded", "failed"]:
            task_logger.info(
                f"文件 {filename} | file_id={file_id} 处理结束，最终状态: {status}"
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
    return {"status": "failed", "file_import_result": {"error": "轮询超时"}}


__all__ = ["upload_files_with_url", "upload_files_with_local"]
