"""Notion 文件上传管理模块。

提供外链上传和本地文件上传两种模式，支持自动重试和指数退避轮询。
"""

import asyncio

import logfire

from core.models.upload import (
    FileUploadRequest,
    FileUploadResult,
    FileUploadWithContent,
)

from .client import get_notion_client
from .models import FileImportError, FileUploadResponse
from .retry_helper import with_retry


async def upload_files_with_local(
    file_list: list[FileUploadWithContent],
    max_retries: int = 3,
) -> list[FileUploadResult]:
    """上传本地文件列表，对失败的文件自动重试。

    Args:
        file_list: 待上传的本地文件列表（含二进制内容）。
        max_retries: 失败文件的最大重试次数，默认 3 次。

    Returns:
        所有文件的上传结果列表（含成功和最终仍失败的）。
    """
    all_results: list[FileUploadResult] = []
    pending_files = file_list
    attempt = 0

    while pending_files and attempt <= max_retries:
        if attempt > 0:
            logfire.warn(
                "本地上传重试 {attempt}/{max_retries}，待处理 {count} 个",
                attempt=attempt,
                max_retries=max_retries,
                count=len(pending_files),
            )
        else:
            logfire.info("开始本地上传，共 {count} 个文件", count=len(pending_files))

        upload_tasks = [_upload_internal_and_wait(each) for each in pending_files]
        batch_results: list[FileUploadResult] = await asyncio.gather(*upload_tasks)

        succeeded = [r for r in batch_results if r.succeeded]
        failed = [r for r in batch_results if not r.succeeded]

        all_results.extend(succeeded)

        if failed and attempt < max_retries:
            failed_urls = {r.url for r in failed}
            pending_files = [f for f in file_list if f.url in failed_urls]
        else:
            if failed:
                logfire.error(
                    "本地上传最终失败 {count} 个: {titles}",
                    count=len(failed),
                    titles=[f.title for f in failed],
                )
            all_results.extend(failed)
            pending_files = []

        attempt += 1

    logfire.info(
        "本地上传完成，成功 {success}/{total}",
        success=sum(1 for f in all_results if f.succeeded),
        total=len(all_results),
    )
    return all_results


@with_retry()
async def _upload_internal_and_wait(
    file_info: FileUploadWithContent,
) -> FileUploadResult:
    """创建 Notion 上传对象并发送本地文件内容。

    Args:
        file_info: 待上传的文件信息（含二进制内容）。

    Returns:
        单个文件的上传结果。
    """
    notion = get_notion_client()
    with logfire.span("上传文件", stock=file_info.stock, title=file_info.title):
        logfire.debug("创建 Notion 上传对象: {title}", title=file_info.title)
    create_result = FileUploadResponse.model_validate(
        await notion.file_uploads.create(
            filename=file_info.title + ".PDF", content_type="application/pdf"
        )
    )
    file_id = create_result.id

    file_succeeded = False
    file_error: str | None = None

    try:
        send_raw = await notion.file_uploads.send(  # pyright: ignore[reportAny]
            file_id,
            file=(file_info.title + ".PDF", file_info.content, "application/pdf"),
        )
        send_result = FileUploadResponse.model_validate(send_raw)
        if send_result.status == "uploaded":
            file_succeeded = True
            logfire.info(
                "上传成功: {title} ({file_id})", title=file_info.title, file_id=file_id
            )
        else:
            file_error = _extract_upload_error(send_result) or "未知错误"
            logfire.error(
                "上传失败: {title} - {error}", title=file_info.title, error=file_error
            )
    except Exception as e:
        logfire.error("上传异常: {title} - {error}", title=file_info.title, error=e)
        file_error = str(e)

    return FileUploadResult(
        stock=file_info.stock,
        url=file_info.url,
        title=file_info.title,
        published_date=file_info.published_date,
        hash_content=file_info.hash_content,
        file_id=file_id,
        succeeded=file_succeeded,
        error=file_error,
    )


async def upload_files_with_url(
    file_list: list[FileUploadRequest],
    max_retries: int = 2,
) -> list[FileUploadResult]:
    """通过外部 URL 上传文件列表，对失败的文件自动重试。

    Args:
        file_list: 待上传的文件信息列表（外链模式）。
        max_retries: 失败文件的最大重试次数，默认 2 次。

    Returns:
        所有文件的上传结果列表。
    """
    all_results: list[FileUploadResult] = []
    pending_files = file_list
    attempt = 0

    while pending_files and attempt <= max_retries:
        if attempt > 0:
            logfire.warn(
                "外链上传重试 {attempt}/{max_retries}，待处理 {count} 个",
                attempt=attempt,
                max_retries=max_retries,
                count=len(pending_files),
            )
        else:
            logfire.info("开始外链上传，共 {count} 个文件", count=len(pending_files))

        upload_tasks = [_upload_external_and_wait(each) for each in pending_files]
        batch_results: list[FileUploadResult] = await asyncio.gather(*upload_tasks)

        succeeded = [r for r in batch_results if r.succeeded]
        failed = [r for r in batch_results if not r.succeeded]

        all_results.extend(succeeded)

        if failed and attempt < max_retries:
            failed_urls = {r.url for r in failed}
            pending_files = [f for f in file_list if f.url in failed_urls]
        else:
            if failed:
                logfire.error(
                    "外链上传最终失败 {count} 个: {titles}",
                    count=len(failed),
                    titles=[f.title for f in failed],
                )
            all_results.extend(failed)
            pending_files = []

        attempt += 1

    logfire.info(
        "外链上传完成，成功 {success}/{total}",
        success=sum(1 for f in all_results if f.succeeded),
        total=len(all_results),
    )
    return all_results


@with_retry()
async def _upload_external_and_wait(file_info: FileUploadRequest) -> FileUploadResult:
    """通过外部 URL 创建上传任务并轮询直到完成。

    Args:
        file_info: 待上传的文件信息（外链模式）。

    Returns:
        单个文件的上传结果。
    """
    notion = get_notion_client()
    with logfire.span("外链上传", stock=file_info.stock, title=file_info.title):
        logfire.debug("外链上传: {title}", title=file_info.title)
    try:
        create_raw = await notion.file_uploads.create(  # pyright: ignore[reportAny]
            mode="external_url",
            filename=file_info.title + ".PDF",
            external_url=file_info.url,
        )
        create_response = FileUploadResponse.model_validate(create_raw)
        file_id = create_response.id

        poll_result = await _poll_upload_status(file_id, file_info.title)

        if poll_result.status == "uploaded":
            logfire.info(
                "外链上传成功: {title} ({file_id})",
                title=file_info.title,
                file_id=file_id,
            )
            return FileUploadResult(
                stock=file_info.stock,
                url=file_info.url,
                title=file_info.title,
                published_date=file_info.published_date,
                hash_content=file_info.hash_content,
                file_id=file_id,
                succeeded=True,
                error=None,
            )

        error_msg = _extract_upload_error(poll_result) or "轮询超时"
        logfire.error(
            "外链上传失败: {title} - {error}", title=file_info.title, error=error_msg
        )
        return FileUploadResult(
            stock=file_info.stock,
            url=file_info.url,
            title=file_info.title,
            published_date=file_info.published_date,
            hash_content=file_info.hash_content,
            file_id=file_id,
            succeeded=False,
            error=error_msg,
        )

    except Exception as e:
        logfire.error("外链上传异常: {title} - {error}", title=file_info.title, error=e)
        return FileUploadResult(
            stock=file_info.stock,
            url=file_info.url,
            title=file_info.title,
            published_date=file_info.published_date,
            hash_content=file_info.hash_content,
            file_id="",
            succeeded=False,
            error=str(e),
        )


def _extract_upload_error(response: FileUploadResponse) -> str | None:
    """从文件上传响应中提取错误信息。

    Args:
        response: Notion 文件上传响应对象。

    Returns:
        错误信息字符串，如果无错误信息则返回 None。
    """
    file_import_result = response.file_import_result
    if file_import_result is None:
        return None
    if isinstance(file_import_result, FileImportError):
        return file_import_result.error.message
    logfire.error(
        "收到了状态不为 `uploaded` 但文件导入结果不为 `error` 的报文：{response}",
        response=response,
    )
    return None


@with_retry()
async def _poll_upload_status(
    file_id: str, filename: str, max_attempts: int = 5
) -> FileUploadResponse:
    """轮询文件上传状态，使用指数退避等待。

    Args:
        file_id: Notion 文件上传任务 ID。
        filename: 原始文件名（用于日志排查）。
        max_attempts: 最大轮询次数，默认 5 次。

    Returns:
        最终的文件上传状态响应（uploaded/failed/超时）。
    """
    notion = get_notion_client()
    intervals = [1, 2, 4, 8, 16]

    for attempt in range(max_attempts):
        response = FileUploadResponse.model_validate(
            await notion.file_uploads.retrieve(file_id)
        )

        if response.status in ("uploaded", "failed"):
            logfire.debug(
                "轮询完成: {filename} 状态={status} (尝试 {attempt})",
                filename=filename,
                status=response.status,
                attempt=attempt + 1,
            )
            return response

        wait_time = intervals[min(attempt, len(intervals) - 1)]
        logfire.debug(
            "轮询中: {filename} 状态={status}，等待 {wait_time}s (尝试 {attempt}/{max_attempts})",
            filename=filename,
            status=response.status,
            wait_time=wait_time,
            attempt=attempt + 1,
            max_attempts=max_attempts,
        )
        await asyncio.sleep(wait_time)

    logfire.warn("轮询超时: {filename} ({file_id})", filename=filename, file_id=file_id)
    return FileUploadResponse(
        id=file_id,
        created_time="",
        status="failed",
    )


__all__ = ["upload_files_with_url", "upload_files_with_local"]
