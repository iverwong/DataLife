"""公告 Notion 页面创建模块。

为上传成功的公告文件创建 Notion 数据流页面。
"""

import asyncio

import logfire

from core.data import get_announcements
from core.models.upload import FileUploadResult
from core.notion.flow_database import create_dataflow_page


async def create_announcement_pages(
    upload_results: list[FileUploadResult],
    stock_id_map: dict[str, str],
) -> list[str]:
    """为上传成功的公告文件批量创建 Notion 数据流页面。

    Args:
        upload_results: 上传成功的文件结果列表。
        stock_id_map: 股票代码到 Notion 页面 ID 的映射。

    Returns:
        成功创建页面对应的唯一 hash_content 列表（已去重）。
    """
    if not upload_results:
        return []

    source_api = f"{get_announcements.__module__}.{get_announcements.__name__}"

    create_tasks: list[asyncio.Task[bool]] = [
        asyncio.create_task(
            create_dataflow_page(
                title=result.title,
                published_date=result.published_date,
                source_api=source_api,
                data_type="公告披露",
                relation=stock_id_map[result.stock],
                attachment_id=result.file_id,
                source_url=result.url,
                content=None,
            )
        )
        for result in upload_results
    ]

    create_results = await asyncio.gather(*create_tasks)

    # 收集成功创建的页面对应的 hash_content
    success_hashes: list[str] = []
    for i, is_success in enumerate(create_results):
        if is_success:
            success_hashes.append(upload_results[i].hash_content)

    # 去重：PDF 分割的多个部分共享相同的 hash_content
    unique_hashes = list(set(success_hashes))

    success_count = sum(create_results)
    failed_count = len(create_results) - success_count
    if failed_count > 0:
        logfire.warn("公告页面创建: 成功 {success}，失败 {failed}", success=success_count, failed=failed_count)
    else:
        logfire.info("公告页面创建: 成功 {count} 条", count=success_count)

    return unique_hashes
