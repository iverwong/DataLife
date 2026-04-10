#!/usr/bin/env python3
"""Rope Use Function: 查找并替换项目中可用函数替代的等价表达式。

用法:
    python scripts/rope_usefunction.py <project_path> <file_path> <func_name> [--offset N] [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     包含目标函数的文件路径（相对于项目根目录）
    func_name     目标函数名
    --offset      精确定位 offset（0-based），优先于 func_name 的自动定位
    --dry-run     仅预览变更

示例:
    python scripts/rope_usefunction.py . src/utils.py square --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.usefunction import UseFunction


def main():
    parser = argparse.ArgumentParser(description="Rope Use Function")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("func_name", help="目标函数名")
    parser.add_argument(
        "--offset",
        type=int,
        help="精确定位 offset（0-based），优先于 func_name 的自动定位",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        source = resource.read()

        try:
            offset = (
                args.offset
                if args.offset is not None
                else find_name_offset(source, args.func_name)
            )
        except ValueError as e:
            print(f"❌ {e}")
            return

        user = UseFunction(project, resource, offset)
        changes = user.get_changes()

        if changes.get_changed_resources():
            print(changes.get_description())
            if not args.dry_run:
                project.do(changes)
                print(f"\n✅ Applied use-function for '{args.func_name}'")
                print(
                    f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
                )
            else:
                print("\n🔍 Dry run — no changes applied")
        else:
            print(f"ℹ️ No replaceable expressions found for '{args.func_name}'")


if __name__ == "__main__":
    main()
