"""Token 计数模块测试。"""
from __future__ import annotations

from core.data.token_counter import count_tokens, slice_tokens


class TestCountTokens:
    """Token 计数测试（保留原有）。"""

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


class TestSliceTokens:
    """slice_tokens 核心测试。"""

    # ── 正向测试 ──

    def test_head_slice(self):
        """start=0 取首部 n 个 token，等价于旧 truncate_to_tokens。"""
        text = "这是测试文本。" * 100  # 约 500+ tokens
        n = 50
        result = slice_tokens(text, 0, n)
        assert count_tokens(result) == n
        assert text.startswith(result)

    def test_tail_slice(self):
        """从尾部截取，等价于旧 truncate_tail_tokens。"""
        text = "这是测试文本。" * 100
        total = count_tokens(text)
        n = 50
        result = slice_tokens(text, total - n, n)
        assert count_tokens(result) == n
        assert text.endswith(result)

    def test_middle_slice(self):
        """从中间位置截取，验证滑动窗口核心能力。"""
        text = "AAAA" * 20 + "BBBB" * 20 + "CCCC" * 20
        total = count_tokens(text)
        # 取中间 1/3
        start = total // 3
        length = total // 3
        result = slice_tokens(text, start, length)
        result_tokens = count_tokens(result)
        assert result_tokens == length
        # 中间段应包含 B 区域内容
        assert "BBBB" in result

    def test_full_text_slice(self):
        """start=0, length>=total 应返回完整文本。"""
        text = "Hello, world!"
        total = count_tokens(text)
        result = slice_tokens(text, 0, total + 100)
        assert result == text

    def test_consecutive_slices_cover_full_text(self):
        """连续无重叠切片拼接后应覆盖全文所有 token（无丢失）。

        fixture 设计：
        - 文本约 300 tokens
        - 窗口大小 100 tokens，步长 100（无 overlap）
        - 预期 3 个切片，拼接后 token 总数 = 原始 token 数
        """
        text = "测试内容。" * 150  # 约 300 tokens
        total = count_tokens(text)
        window = 100
        slices: list[str] = []
        pos = 0
        while pos < total:
            s = slice_tokens(text, pos, window)
            if not s:
                break
            slices.append(s)
            pos += count_tokens(s)
        # 拼接后 token 总数应等于原始 token 数
        reconstructed = "".join(slices)
        assert count_tokens(reconstructed) == total

    def test_overlap_slices_no_content_loss(self):
        """带 overlap 的滑动窗口切片不应丢失内容。

        fixture 设计：
        - 文本约 300 tokens
        - 窗口 120 tokens，步长 100（overlap 20）
        - 每个窗口实际调用 slice_tokens，收集覆盖的 token index
        - 去重后 token 总数 = 原始 token 数
        """
        text = "验证内容。" * 150  # 约 300 tokens
        total = count_tokens(text)
        window = 120
        step = 100  # overlap = 20
        covered_tokens: set[int] = set()
        pos = 0
        while pos < total:
            segment = slice_tokens(text, pos, window)
            seg_len = count_tokens(segment)
            for i in range(pos, pos + seg_len):
                covered_tokens.add(i)
            pos += step
        assert len(covered_tokens) == total

    # ── 边界测试 ──

    def test_empty_text(self):
        """空文本应返回空字符串。"""
        assert slice_tokens("", 0, 10) == ""

    def test_zero_length(self):
        """length=0 应返回空字符串。"""
        assert slice_tokens("Hello", 0, 0) == ""

    def test_negative_length(self):
        """length<0 应返回空字符串。"""
        assert slice_tokens("Hello", 0, -5) == ""

    def test_negative_start(self):
        """start<0 应修正为 0。"""
        text = "Hello, world!"
        result = slice_tokens(text, -5, 3)
        expected = slice_tokens(text, 0, 3)
        assert result == expected

    def test_start_beyond_total(self):
        """start >= total_tokens 应返回空字符串。"""
        text = "Hello"
        total = count_tokens(text)
        assert slice_tokens(text, total, 10) == ""
        assert slice_tokens(text, total + 100, 10) == ""

    def test_length_exceeds_remaining(self):
        """length 超出剩余 token 数时截取到末尾。"""
        text = "Hello, world!"
        total = count_tokens(text)
        result = slice_tokens(text, total - 2, 100)
        assert count_tokens(result) == 2

    def test_valid_utf8(self):
        """截取后的文本应是有效的 UTF-8 字符串。"""
        text = "中文混合English测试" * 50
        result = slice_tokens(text, 10, 20)
        assert isinstance(result, str)
        result.encode("utf-8")
