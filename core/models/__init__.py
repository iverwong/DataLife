from typing import Literal, NewType

NotionDate = NewType("NotionDate", str)
"""ISO-8601 格式的日期字符串，用于 Notion API 交互。"""

UpdateRecordKey = Literal["business", "announcements"]
"""数据库更新记录的业务键类型。"""

__all__ = [
    "NotionDate",
    "UpdateRecordKey",
]
