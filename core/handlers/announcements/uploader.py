"""公告文件上传模块。

负责将公告通过外链方式上传到 Notion。
（已清理：移除 PDF 分割上传功能）
"""

from dataclasses import dataclass

import logfire

from core.models.announcement import AnnouncementWithHash
from core.models.upload import FileUploadRequest, FileUploadResult
from core.notion.upload_file import upload_files_with_url


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
) -> UploadBatchResult:
    """上传公告附件（外链方式）。

    Args:
        announcements: 待上传的公告及哈希列表。

    Returns:
        包含成功和失败文件列表的批量上传结果。
    """
    logfire.info("公告上传: 共 {count} 个", count=len(announcements))

    # 构建外链上传请求
    requests = [
        FileUploadRequest(
            url=item.announcement.url,
            title=item.announcement.title,
            stock=item.announcement.stock,
            published_date=item.announcement.published_date,
            hash_content=item.hash_value,
        )
        for item in announcements
    ]

    # 执行上传
    results = await upload_files_with_url(requests)

    # 汇总结果
    succeeded = [r for r in results if r.succeeded]
    failed = [r for r in results if not r.succeeded]

    if failed:
        logfire.error("上传失败: {titles}", titles=[f.title for f in failed])

    return UploadBatchResult(succeeded=succeeded, failed=failed)
