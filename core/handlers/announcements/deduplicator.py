"""公告去重模块。

基于 xxhash 对公告进行去重，返回数据库中尚不存在的公告列表。
"""

import logfire

from core.data.announcement import Announcement
from core.db import HashContent, HashContentWithHash, check_hash
from core.models.announcement import AnnouncementWithHash


async def deduplicate_announcements(
    announcements: list[Announcement],
) -> list[AnnouncementWithHash]:
    """对公告列表进行哈希去重，过滤掉已处理过的公告。

    Args:
        announcements: 原始公告列表。

    Returns:
        去重后的公告及其哈希值列表，仅包含数据库中尚不存在的公告。
    """
    if not announcements:
        return []

    # 构建去重内容列表
    hash_contents: list[HashContent] = [
        HashContent(
            data_type="announcements",
            content=f"{ann.stock}-{ann.id}-{ann.title}",
        )
        for ann in announcements
    ]

    # 检查哈希去重
    filtered: list[HashContentWithHash] = await check_hash(hash_contents)

    logfire.info("公告去重: {total} -> {filtered} 条", total=len(hash_contents), filtered=len(filtered))

    if not filtered:
        return []

    # 构建 content -> hash_value 映射表
    hash_map: dict[str, str] = {item.content: item.hash_value for item in filtered}

    # 过滤公告列表：只保留在 hash_map 中的公告
    result: list[AnnouncementWithHash] = []
    for ann, hc in zip(announcements, hash_contents):
        if hc.content in hash_map:
            result.append(AnnouncementWithHash(
                announcement=ann,
                hash_value=hash_map[hc.content],
            ))

    return result
