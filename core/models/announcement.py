"""公告相关的共享领域模型。"""

from dataclasses import dataclass

from core.data.announcement import Announcement


@dataclass(frozen=True)
class AnnouncementWithHash:
    """公告与其去重哈希值的关联对象。

    Attributes:
        announcement: 原始公告数据。
        hash_value: 基于公告内容计算的 xxhash 去重哈希值。
    """

    announcement: Announcement
    hash_value: str
