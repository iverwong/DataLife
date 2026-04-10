#!/usr/bin/env python3
"""公共工具函数：Rope 项目上下文管理、符号 offset 查找、行号转 offset。"""

import re
from contextlib import contextmanager

from rope.base.project import Project


@contextmanager
def rope_project(path: str, ropefolder: str = ".ropeproject"):
    """创建并管理 Rope 项目上下文，自动清除缓存并关闭。

    Args:
        path: 项目根目录路径
        ropefolder: Rope 配置文件夹名，传 None 可禁用
    """
    project = Project(path, ropefolder=ropefolder)
    try:
        project.validate(project.root)
        yield project
    finally:
        project.close()


def find_name_offset(source: str, name: str) -> int:
    """查找符号在源码中的 offset，优先匹配定义处（def/class/赋值）。

    局限性:
        - 基于正则匹配，可能命中注释或字符串中的文本
        - 多个同名定义时只返回第一个匹配
        - 如需精确定位，请使用各脚本的 --offset 参数直接指定

    Raises:
        ValueError: 符号未找到
    """
    for pattern in [
        rf"\bdef\s+({re.escape(name)})\b",
        rf"\bclass\s+({re.escape(name)})\b",
        rf"\b({re.escape(name)})\s*=",
    ]:
        m = re.search(pattern, source)
        if m:
            return m.start(1)
    offset = source.find(name)
    if offset == -1:
        raise ValueError(f"Symbol '{name}' not found in source")
    return offset


def lines_to_offsets(source: str, start_line: int, end_line: int) -> tuple[int, int]:
    """将行号（1-based，包含）转换为 Rope 所需的字符偏移量。

    正确处理 LF / CRLF 换行符，确保 end offset 落在
    有效内容字符之后、换行符之前。
    """
    lines = source.splitlines(keepends=True)
    start = sum(len(lines[i]) for i in range(start_line - 1))
    end = sum(len(lines[i]) for i in range(end_line))
    # 回退换行符，使 end 指向行内最后一个有效字符之后
    while end > start and source[end - 1] in ("\r", "\n"):
        end -= 1
    return start, end
