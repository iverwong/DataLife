from datetime import datetime
from unittest.mock import patch

from core.business_data_handler import _should_update_half_year


def _patch_datetime(now_value):
    """mock datetime.now() 同时保留 strptime 和构造器的真实行为"""
    p = patch("core.business_data_handler.datetime", wraps=datetime)
    mock_dt = p.start()
    mock_dt.now.return_value = now_value
    return p, mock_dt


class TestShouldUpdateHalfYear:
    def test_none_returns_true(self):
        """从未更新过，应当返回 True"""
        assert _should_update_half_year(None) is True

    def test_empty_string_returns_true(self):
        """空字符串视同未更新"""
        assert _should_update_half_year("") is True

    def test_q2_before_next_year(self):
        """上次更新为 6/30（Q2），在下一年1月1日00:00:00之前不需要更新"""
        p, _ = _patch_datetime(datetime(2025, 12, 31, 23, 59, 59))
        try:
            assert _should_update_half_year("2025-06-30") is False
        finally:
            p.stop()

    def test_q2_after_next_year(self):
        """上次更新为 6/30（Q2），到了下一年1月1日00:00:00应当更新"""
        p, _ = _patch_datetime(datetime(2026, 1, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-06-30") is True
        finally:
            p.stop()

    def test_q2_exactly_next_year_boundary(self):
        """上次更新为 6/30（Q2），恰好在1月1日00:00:00边界上应当更新（>=）"""
        p, _ = _patch_datetime(datetime(2026, 1, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-06-30") is True
        finally:
            p.stop()

    def test_q4_before_next_july(self):
        """上次更新为 12/31（Q4），在下一年7月1日00:00:00之前不需要更新"""
        p, _ = _patch_datetime(datetime(2026, 6, 30, 23, 59, 59))
        try:
            assert _should_update_half_year("2025-12-31") is False
        finally:
            p.stop()

    def test_q4_after_next_july(self):
        """上次更新为 12/31（Q4），到了下一年7月1日00:00:00应当更新"""
        p, _ = _patch_datetime(datetime(2026, 7, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-12-31") is True
        finally:
            p.stop()

    def test_q4_exactly_july_boundary(self):
        """上次更新为 12/31（Q4），恰好在7月1日00:00:00边界上应当更新（>=）"""
        p, _ = _patch_datetime(datetime(2026, 7, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-12-31") is True
        finally:
            p.stop()

    def test_non_quarter_end_returns_false(self):
        """非季度末日期（如 3/15）应返回 False 并记录错误"""
        assert _should_update_half_year("2025-03-15") is False

    def test_iso_datetime_string_extracts_date_part(self):
        """带时间戳的 ISO 字符串，只取前10字符作为日期"""
        p, _ = _patch_datetime(datetime(2026, 1, 1, 0, 0, 0))
        try:
            assert _should_update_half_year("2025-06-30T12:00:00.000+08:00") is True
        finally:
            p.stop()
