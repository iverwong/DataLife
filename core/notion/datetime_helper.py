"""
系统中所有的字符串存储的时间逻辑都按该转换要求进行转换
"""

from datetime import date, datetime, timedelta, timezone

from ..models import NotionDate

TZ = timezone(timedelta(hours=8))


def cover_datetime_to_notion_date(input_: datetime | date) -> NotionDate:
    """
    将Python的datetime或date对象转换为NotionDate对象。

    参数:
        input_ (datetime | date): 需要转换的日期或时间对象。可以是datetime类型或date类型。

    返回:
        NotionDate: 转换后的NotionDate对象。如果输入是date类型，则直接转换为字符串格式；
                    如果输入是datetime类型，则将其转换为带时区信息的ISO格式字符串。
    """
    if isinstance(input_, datetime):
        return NotionDate(input_.astimezone(TZ).isoformat(timespec="milliseconds"))
    return NotionDate(str(input_))


def cover_notion_date_to_datetime(input: NotionDate) -> datetime:
    """
    将NotionDate类型的日期转换为datetime对象。

    参数:
        input (NotionDate): 需要转换的NotionDate对象，应为ISO格式的字符串。

    返回:
        datetime: 转换后的datetime对象。
    """
    return datetime.fromisoformat(input)
