#!/usr/bin/env python3
"""Rope Introduce Parameter: 将函数体内的表达式提升为新参数。

用法:
    python scripts/rope_introduce_parameter.py <project_path> <file_path> <func_name> <param_name> <offset> [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     文件路径（相对于项目根目录）
    func_name     目标函数名（仅用于日志提示）
    param_name    新参数名称
    offset        表达式起始 offset（0-based，指向函数体内要提升的表达式）
    --dry-run     仅预览变更

示例:
    # 将 process() 中 offset 10 处的表达式提升为参数 threshold
    python scripts/rope_introduce_parameter.py . src/utils.py process threshold 10
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import rope_project
from rope.base import libutils
from rope.refactor.introduce_parameter import IntroduceParameter


def main():
    parser = argparse.ArgumentParser(description="Rope Introduce Parameter")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument(
        "func_name", help="目标函数名（仅用于日志提示，定位依赖 offset 参数）"
    )
    parser.add_argument("param_name", help="新参数名称")
    parser.add_argument(
        "offset",
        type=int,
        help="表达式起始 offset（0-based，指向函数体内要提升的表达式）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)

        try:
            introducer = IntroduceParameter(project, resource, args.offset)
            changes = introducer.get_changes(args.param_name)
        except Exception as e:
            print(f"❌ IntroduceParameter 失败: {e}")
            print("   注意：offset 必须指向函数体内要提升为参数的表达式起始位置")
            print("   end_offset 参数仅用于日志，Rope API 只需 start_offset")
            return

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(
                f"\n✅ Introduced parameter '{args.param_name}' for '{args.func_name}'"
            )
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
