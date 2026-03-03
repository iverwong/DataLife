"""Token 计数模块测试。"""
from __future__ import annotations

import pytest

from core.data.token_counter import count_tokens, truncate_to_tokens


class TestCountTokens:
    """Token 计数测试。"""

    def test_empty_string(self):
        """空字符串应返回 0。"""
        assert count_tokens("") == 0

    def test_english_text(self):
        """英文文本的 token 数应大于 0。"""
        result = count_tokens("Hello, world!")
        assert result > 0

    def test_chinese_text(self):
        """中文文本的 token 数应大于 0。"""
        result = count_tokens("这是一段中文测试文本。")
        assert result > 0

    def test_longer_text_more_tokens(self):
        """更长的文本应有更多 token。"""
        short = count_tokens("短文本")
        long = count_tokens("这是一段更长的文本，包含更多的内容和信息。" * 10)
        assert long > short


class TestTruncateToTokens:
    """Token 截断测试。"""

    def test_short_text_unchanged(self):
        """token 数未超限的文本应保持不变。"""
        text = "Hello"
        result = truncate_to_tokens(text, max_tokens=100)
        assert result == text

    def test_long_text_truncated(self):
        """超长文本应被截断到 max_tokens 以内。"""
        text = "这是测试文本。" * 1000
        result = truncate_to_tokens(text, max_tokens=50)
        assert count_tokens(result) <= 50

    def test_truncated_text_is_valid_utf8(self):
        """截断后的文本应是有效的 UTF-8 字符串。"""
        text = "中文混合English测试" * 100
        result = truncate_to_tokens(text, max_tokens=20)
        assert isinstance(result, str)
        result.encode("utf-8")
