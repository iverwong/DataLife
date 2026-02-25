"""公告文件上传模块。

负责将公告按大小/关键词分类，分别通过外链和本地上传两种方式上传到 Notion。
"""

import asyncio
from dataclasses import dataclass

from loguru import logger

from core.data import split_pdf
from core.models.announcement import AnnouncementWithHash
from core.models.upload import (
    FileUploadRequest,
    FileUploadResult,
    FileUploadWithContent,
)
from core.notion.upload_file import upload_files_with_local, upload_files_with_url

SPLIT_KEYWORDS = ["年度报告", "年报", "中期"]
"""需要 PDF 分割上传的关键词列表。"""


@dataclass(frozen=True)
class UploadBatchResult:
    """批量上传结果。

    Attributes:
        succeeded: 上传成功的文件结果列表。
        failed: 上传失败的文件结果列表。
    """

    succeeded: list[FileUploadResult]
    failed: list[FileUploadResult]


async def upload_announcement_files(
    announcements: list[AnnouncementWithHash],
    split_keywords: list[str] | None = None,
    size_threshold: int = 200,
) -> UploadBatchResult:
    """分类并上传公告附件。

    小文件且不含关键词 -> 外链上传；大文件或含关键词 -> PDF 分割后本地上传。

    Args:
        announcements: 待上传的公告及哈希列表。
        split_keywords: 触发 PDF 分割的关键词列表，默认使用模块常量。
        size_threshold: 文件大小阈值（KB），超过则触发分割上传。

    Returns:
        包含成功和失败文件列表的批量上传结果。
    """
    if split_keywords is None:
        split_keywords = SPLIT_KEYWORDS

    # 分类：小文件（外链上传）vs 大文件（本地分割上传）
    small_files: list[AnnouncementWithHash] = []
    large_files: list[AnnouncementWithHash] = []

    for item in announcements:
        ann = item.announcement
        needs_split = ann.size > size_threshold or any(
            kw in ann.title for kw in split_keywords
        )
        if needs_split:
            large_files.append(item)
        else:
            small_files.append(item)

    logger.info(
        "公告分类: 外链 {} 个，分割上传 {} 个", len(small_files), len(large_files)
    )

    # 构建外链上传请求并启动任务
    external_requests = [
        FileUploadRequest(
            url=item.announcement.url,
            title=item.announcement.title,
            stock=item.announcement.stock,
            published_date=item.announcement.published_date,
            hash_content=item.hash_value,
        )
        for item in small_files
    ]
    external_task = asyncio.create_task(upload_files_with_url(external_requests))

    # 分割大文件并构建本地上传请求
    local_requests: list[FileUploadWithContent] = []
    if large_files:
        split_results = await split_pdf(large_files)
        local_requests = [
            FileUploadWithContent(
                url=ann_with_content.url,
                title=ann_with_content.title,
                stock=ann_with_content.stock,
                published_date=ann_with_content.published_date,
                hash_content=original.hash_value,
                content=ann_with_content.content,
            )
            for ann_with_content, original in split_results
        ]

    local_task = asyncio.create_task(upload_files_with_local(local_requests))

    # 等待两种上传任务完成
    external_results, local_results = await asyncio.gather(external_task, local_task)

    # 汇总结果
    succeeded, failed = _categorize_upload_results(external_results, local_results)

    return UploadBatchResult(succeeded=succeeded, failed=failed)


def _categorize_upload_results(
    external_results: list[FileUploadResult],
    local_results: list[FileUploadResult],
) -> tuple[list[FileUploadResult], list[FileUploadResult]]:
    """将上传结果分为成功和失败两组。

    外链上传结果直接按 succeeded 字段分类。本地上传结果按 hash_content
    分组，同一 hash_content 的所有分块必须全部成功才算成功。

    Args:
        external_results: 外链上传结果列表。
        local_results: 本地上传结果列表。

    Returns:
        (成功列表, 失败列表) 元组。
    """
    succeeded: list[FileUploadResult] = [r for r in external_results if r.succeeded]
    failed: list[FileUploadResult] = [r for r in external_results if not r.succeeded]

    # 本地上传：按 hash_content 分组，全部成功才算成功
    hash_groups: dict[str, list[FileUploadResult]] = {}
    for result in local_results:
        hash_groups.setdefault(result.hash_content, []).append(result)

    for group in hash_groups.values():
        if all(item.succeeded for item in group):
            succeeded.extend(group)
        else:
            failed.extend(group)

    if failed:
        logger.error("上传失败: {}", [f.title for f in failed])

    return succeeded, failed
