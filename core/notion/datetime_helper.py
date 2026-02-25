"""日期与 Notion 日期字符串之间的转换工具。

系统中所有的字符串存储的时间逻辑都按该转换要求进行转换。
"""

from datetime import date, datetime, timedelta, timezone

from ..models import NotionDate

TZ = timezone(timedelta(hours=8))


def convert_datetime_to_notion_date(date_input: datetime | date) -> NotionDate:
    """将 Python 日期对象转换为 Notion 日期字符串。

    Args:
        date_input: 需要转换的日期或时间对象。

    Returns:
        ISO-8601 格式的 Notion 日期字符串。datetime 类型带时区信息，
        date 类型为纯日期字符串。
    """
    if isinstance(date_input, datetime):
        return NotionDate(date_input.astimezone(TZ).isoformat(timespec="milliseconds"))
    return NotionDate(str(date_input))


def convert_notion_date_to_datetime(notion_date: NotionDate) -> datetime:
    """将 Notion 日期字符串转换为 datetime 对象。

    Args:
        notion_date: ISO-8601 格式的 Notion 日期字符串。

    Returns:
        解析后的 datetime 对象。
    """
    return datetime.fromisoformat(notion_date)


# 向后兼容别名（过渡期后移除）
cover_datetime_to_notion_date = convert_datetime_to_notion_date
cover_notion_date_to_datetime = convert_notion_date_to_datetime
