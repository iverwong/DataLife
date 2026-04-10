#!/usr/bin/env python3
"""Rope Move: 移动函数/类/模块到目标模块。

用法:
    # 移动符号（函数/类/变量）到目标模块
    python scripts/rope_move.py <project_path> <source_file> <dest_file> --symbol <symbol_name> [--dry-run]

    # 移动整个模块到目标目录/包
    python scripts/rope_move.py <project_path> <source_file> <dest_dir> [--dry-run]

参数:
    project_path  项目根目录路径
    source_file   源文件路径（相对于项目根目录）
    dest_file     目标文件路径（相对于项目根目录）
    --symbol      要移动的符号名（省略则移动整个模块）
    --dry-run     仅预览变更

移动方法说明:
    当 --symbol 指向类内方法时，Rope 执行 MoveMethod 重构，
    将该方法移至其某个参数所引用对象的类上。
    此时 dest 应为该参数的名称（字符串），而非目标文件路径。
    示例：方法 def render(self, ctx): ... 中，用 dest=ctx 表示
    将 render 移至 ctx 所引用的类上。

示例:
    python scripts/rope_move.py . src/utils.py src/helpers.py --symbol helper_func
    python scripts/rope_move.py . src/old_module.py src/new_package/
    python scripts/rope_move.py . src/service.py ctx --symbol render
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.move import MoveMethod, create_move


def main():
    parser = argparse.ArgumentParser(description="Rope Move")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("source_file", help="源文件路径（相对于项目根目录）")
    parser.add_argument(
        "dest", help="目标文件路径（移动符号/模块）或参数名（MoveMethod）"
    )
    parser.add_argument(
        "--symbol", default=None, help="要移动的符号名（省略则移动整个模块）"
    )
    parser.add_argument(
        "--offset",
        type=int,
        help="精确定位 offset（0-based），优先于 --symbol 的自动定位",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.source_file)

        # 1) 仅传 source_file + dest：移动整个模块
        #    dest 应为目标目录（包），MoveModule 期望 Folder 资源
        if args.symbol is None:
            dest_resource = libutils.path_to_resource(project, args.dest)
            if not dest_resource.is_folder():
                print(
                    f"❌ Module move requires a directory/package as destination, got file: {args.dest}"
                )
                return
            changes = create_move(project, resource, None).get_changes(dest_resource)

        # 2) 传入 symbol_name：移动符号（函数/类/变量/方法）
        else:
            source = resource.read()
            try:
                offset = (
                    args.offset
                    if args.offset is not None
                    else find_name_offset(source, args.symbol)
                )
            except ValueError as e:
                print(f"❌ {e} in {args.source_file}")
                return

            mover = create_move(project, resource, offset)

            if isinstance(mover, MoveMethod):
                # MoveMethod：dest 是目标参数名（字符串），不是文件路径
                changes = mover.get_changes(args.dest)
            else:
                # MoveGlobal：dest 是目标模块文件
                changes = mover.get_changes(
                    libutils.path_to_resource(project, args.dest)
                )

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            what = args.symbol or "<module>"
            print(f"\n✅ Moved {what} from {args.source_file} to {args.dest}")
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
