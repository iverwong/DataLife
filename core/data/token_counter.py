"""Token 计数工具模块。

封装 tiktoken 的 token 计数逻辑，提供简洁接口。
使用 cl100k_base 编码（兼容大多数主流 LLM）。
"""

from __future__ import annotations

import tiktoken


# 使用 cl100k_base 编码，兼容 GPT-4 / DeepSeek 等主流模型
_ENCODING_NAME: str = "cl100k_base"
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """获取或懒加载 tiktoken 编码器（单例）。

    Returns:
        tiktoken.Encoding 实例。
    """
    ...


def count_tokens(text: str) -> int:
    """计算文本的 token 数。

    Args:
        text: 待计数的文本。

    Returns:
        token 数量。
    """
    ...


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """将文本截断到指定 token 数。

    在 token 边界处截断，不会切断 UTF-8 字符。

    Args:
        text: 待截断文本。
        max_tokens: 最大 token 数。

    Returns:
        截断后的文本。
    """
    ...
