from datetime import date, datetime, timedelta, timezone

from core.notion.datetime_helper import (
    TZ,
    cover_datetime_to_notion_date,
    cover_notion_date_to_datetime,
)


class TestCoverDatetimeToNotionDate:
    def test_date_input(self):
        d = date(2025, 6, 30)
        result = cover_datetime_to_notion_date(d)
        assert result == "2025-06-30"

    def test_datetime_naive(self):
        """datetime 也是 date 的子类，isinstance(dt, date) 为 True，走 str() 分支"""
        dt = datetime(2025, 1, 15, 10, 30, 0)
        result = cover_datetime_to_notion_date(dt)
        # 实际走 str() 分支，结果等同 str(dt)
        assert result == str(dt)
        parsed = datetime.fromisoformat(result)
        assert parsed.hour == 10
        assert parsed.minute == 30

    def test_datetime_with_utc(self):
        """带时区的 datetime 同样走 str() 分支，保留原始时区"""
        dt = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = cover_datetime_to_notion_date(dt)
        assert result == str(dt)
        parsed = datetime.fromisoformat(result)
        assert parsed.hour == 0
        assert parsed.utcoffset() == timedelta(hours=0)

    def test_datetime_with_tz8(self):
        dt = datetime(2025, 7, 20, 15, 45, 30, tzinfo=TZ)
        result = cover_datetime_to_notion_date(dt)
        parsed = datetime.fromisoformat(result)
        assert parsed.hour == 15
        assert parsed.minute == 45
        assert parsed.second == 30

    def test_microseconds_in_str(self):
        """str(datetime) 保留微秒精度"""
        dt = datetime(2025, 1, 1, 12, 0, 0, 123456, tzinfo=TZ)
        result = cover_datetime_to_notion_date(dt)
        assert ".123456" in result

    def test_date_is_subclass_of_date_not_datetime(self):
        """确保 date 走 date 分支而非 datetime 分支（datetime 是 date 的子类，顺序重要）"""
        d = date(2025, 12, 31)
        result = cover_datetime_to_notion_date(d)
        # date 分支直接 str()，不应包含时区信息
        assert "T" not in result
        assert "+" not in result


class TestCoverNotionDateToDatetime:
    def test_date_only_string(self):
        result = cover_notion_date_to_datetime("2025-06-30")
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 30

    def test_iso_with_timezone(self):
        result = cover_notion_date_to_datetime("2025-03-01T08:00:00.000+08:00")
        assert result.hour == 8
        assert result.utcoffset() == timedelta(hours=8)

    def test_roundtrip_datetime(self):
        """datetime -> NotionDate -> datetime 往返一致"""
        original = datetime(2025, 5, 10, 14, 30, 0, tzinfo=TZ)
        notion_date = cover_datetime_to_notion_date(original)
        restored = cover_notion_date_to_datetime(notion_date)
        assert restored.year == original.year
        assert restored.month == original.month
        assert restored.day == original.day
        assert restored.hour == original.hour
        assert restored.minute == original.minute

    def test_roundtrip_date(self):
        """date -> NotionDate -> datetime 往返，日期部分一致"""
        original = date(2025, 11, 1)
        notion_date = cover_datetime_to_notion_date(original)
        restored = cover_notion_date_to_datetime(notion_date)
        assert restored.year == 2025
        assert restored.month == 11
        assert restored.day == 1
