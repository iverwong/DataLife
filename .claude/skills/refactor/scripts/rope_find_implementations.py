#!/usr/bin/env python3
"""Rope Find Implementations: 查找方法/类的所有实现。

与 find_occurrences 互补：find_occurrences 查找引用，
find_implementations 查找子类实现（继承链追踪）。

用法:
    python scripts/rope_find_implementations.py <project_path> <file_path> <name> [--offset N]

参数:
    project_path  项目根目录路径
    file_path     文件路径（相对于项目根目录）
    name          要查找实现的符号名（类或方法）
    --offset      精确定位 offset（0-based）

示例:
    python scripts/rope_find_implementations.py . src/base.py BaseHandler
    python scripts/rope_find_implementations.py . src/base.py process
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.contrib.findit import find_implementations


def main():
    parser = argparse.ArgumentParser(description="Rope Find Implementations")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("name", help="要查找实现的符号名")
    parser.add_argument("--offset", type=int, help="精确定位 offset（0-based）")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        source = resource.read()

        try:
            offset = (
                args.offset
                if args.offset is not None
                else find_name_offset(source, args.name)
            )
        except ValueError:
            print(f"❌ Symbol '{args.name}' not found")
            return

        try:
            implementations = find_implementations(project, resource, offset)
        except Exception as e:
            msg = str(e)
            if "Not a method" in msg:
                print(
                    f"❌ '{args.name}' 不是方法，find_implementations 仅支持类/实例方法"
                )
                print("   Rope 的 find_implementations 追踪继承链中的方法覆写")
                print(
                    "   对于 Protocol/ABC 类本身，请改用 rope_find_occurrences.py 查找引用"
                )
                return
            raise

        print(f"Found {len(implementations)} implementation(s) of '{args.name}':\n")
        for impl in implementations:
            res = impl.resource
            lineno = impl.lineno
            src_lines = res.read().splitlines()
            line_text = (
                src_lines[lineno - 1].strip() if lineno <= len(src_lines) else ""
            )
            unsure_tag = " [unsure]" if impl.unsure else ""
            print(f"  {res.path}:{lineno}  {line_text}{unsure_tag}")


if __name__ == "__main__":
    main()
