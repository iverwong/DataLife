#!/usr/bin/env python3
"""Rope Inline: 内联方法/变量/参数。

用法:
    # 默认：通过 name 定位（优先 def/赋值），对整项目进行 inline
    python scripts/rope_inline.py <project_path> <file_path> <name> [--remove] [--only-current] [--dry-run]

    # 精确定位：当同名符号较多、或要 inline 参数/调用点时，直接指定 offset
    python scripts/rope_inline.py <project_path> <file_path> <name> --offset <offset> [--remove] [--only-current] [--dry-run]

参数:
    project_path   项目根目录路径
    file_path      文件路径（相对于项目根目录）
    name           目标符号名（用于辅助提示与默认定位）
    --offset       直接指定字符 offset（0-based），用于精确定位 inline 位置
    --remove       内联后删除原始定义（默认保留）
    --only-current 仅内联当前出现，不影响其他使用
    --dry-run      仅预览变更
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.inline import create_inline


def main():
    parser = argparse.ArgumentParser(description="Rope Inline")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("name", help="要内联的符号名")
    parser.add_argument("--offset", type=int, help="精确定位 offset（0-based），优先于 name 的自动定位")
    parser.add_argument("--remove", action="store_true", help="内联后删除原始定义")
    parser.add_argument("--only-current", action="store_true", help="仅内联当前出现")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
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
        except ValueError as e:
            print(f"❌ {e}")
            return

        try:
            inliner = create_inline(project, resource, offset)
            changes = inliner.get_changes(
                remove=args.remove, only_current=args.only_current
            )
            print(changes.get_description())
        except AttributeError as e:
            if "'NoneType'" in str(e):
                print(f"❌ Rope 无法读取 '{args.name}' 的定义源码")
                print(
                    "   可能原因：符号定义在项目外部（第三方库/stdlib）或 offset 指向了 import 语句"
                )
                print("   建议：用 --offset 精确指向本地定义处，或 fallback 到手动编辑")
                return
            raise

        if not args.dry_run:
            project.do(changes)
            print(f"\n✅ Inlined '{args.name}'")
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
