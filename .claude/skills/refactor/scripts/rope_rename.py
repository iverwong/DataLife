#!/usr/bin/env python3
"""Rope Rename: 安全重命名 Python 符号，自动更新所有引用。

用法:
    python scripts/rope_rename.py <project_path> <file_path> <old_name> <new_name> [--docs] [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     包含目标符号的文件路径（相对于项目根目录）
    old_name      要重命名的符号名称
    new_name      新名称
    --docs        同时重命名注释和字符串中的出现（默认关闭）
    --dry-run     仅预览变更，不实际执行
    --unsure      重命名不确定的匹配项（动态引用等）

示例:
    python scripts/rope_rename.py . src/models.py OldClass NewClass --docs
    python scripts/rope_rename.py . src/utils.py old_func new_func --dry-run
    python scripts/rope_rename.py . src/api.py handler new_handler --resources src/api.py,src/routes.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.rename import Rename


def main():
    parser = argparse.ArgumentParser(description="Rope Rename")
    parser.add_argument("project_path", help="项目根目录")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("old_name", help="原名称")
    parser.add_argument("new_name", help="新名称")
    parser.add_argument(
        "--offset",
        type=int,
        help="精确定位 offset（0-based），优先于 old_name 的自动定位",
    )
    parser.add_argument(
        "--docs", action="store_true", help="重命名注释和字符串中的出现"
    )
    parser.add_argument("--unsure", action="store_true", help="重命名不确定的匹配")
    parser.add_argument(
        "--resources", help="限制分析范围，逗号分隔的文件路径（相对于项目根目录）"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        source = resource.read()
        offset = (
            args.offset
            if args.offset is not None
            else find_name_offset(source, args.old_name)
        )

        renamer = Rename(project, resource, offset)

        kwargs: dict = {"docs": args.docs}
        if args.unsure:
            kwargs["unsure"] = lambda occ: True
        if args.resources:
            kwargs["resources"] = [
                libutils.path_to_resource(project, p.strip())
                for p in args.resources.split(",")
            ]

        changes = renamer.get_changes(args.new_name, **kwargs)

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(f"\n✅ Renamed '{args.old_name}' -> '{args.new_name}'")
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
