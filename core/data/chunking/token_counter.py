"""Token 计数工具模块。

封装 tiktoken 的 token 计数逻辑，提供简洁接口。
使用 cl100k_base 编码（兼容大多数主流 LLM）。
"""

from __future__ import annotations

import tiktoken

# 使用 cl100k_base 编码，兼容 GPT-4 / DeepSeek 等主流模型
_ENCODING_NAME: str = "cl100k_base"
_encoder: tiktoken.Encoding | None = None


def get_encoder() -> tiktoken.Encoding:
    """获取或懒加载 tiktoken 编码器（单例）。

    Returns:
        tiktoken.Encoding 实例。
    """
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding(_ENCODING_NAME)
    return _encoder


def count_tokens(text: str) -> int:
    """计算文本的 token 数。

    Args:
        text: 待计数的文本。

    Returns:
        token 数量。
    """
    if not text:
        return 0
    encoder = get_encoder()
    tokens = encoder.encode(text)
    return len(tokens)


def slice_tokens(text: str, start: int, length: int) -> str:
    """从文本的第 start 个 token 开始，截取 length 个 token 对应的文本。

    在 token 边界处截断，不会切断 UTF-8 字符。
    支持滑动窗口、首部截取、尾部截取等所有切片场景。

    等价关系：
    - 取首部 n 个 token: slice_tokens(text, 0, n)
    - 取尾部 n 个 token: slice_tokens(text, count_tokens(text) - n, n)

    边界行为：
    - start < 0: 自动修正为 0
    - start >= total_tokens: 返回 ""
    - start + length > total_tokens: 截取到文本末尾（不报错）
    - length <= 0: 返回 ""
    - text 为空: 返回 ""

    Args:
        text: 待截取的文本。
        start: 起始 token 索引（0-based）。
        length: 截取的 token 数量。

    Returns:
        截取后的文本。
    """
    # 边界条件处理
    if not text:
        return ""
    if length <= 0:
        return ""

    encoder = get_encoder()
    tokens: list[int] = encoder.encode(text)
    total_tokens = len(tokens)

    if start >= total_tokens:
        return ""

    # 修正负数 start
    if start < 0:
        start = 0

    # 处理超出范围的情况：截取到末尾
    end = start + length
    if end > total_tokens:
        end = total_tokens

    # 切片并解码
    sliced_tokens = tokens[start:end]
    return encoder.decode(sliced_tokens)
