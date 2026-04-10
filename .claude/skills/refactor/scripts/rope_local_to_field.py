#!/usr/bin/env python3
"""Rope Local to Field: 将局部变量提升为实例字段。

将方法内的局部变量转换为 self.xxx 实例属性，
自动更新方法内所有引用。

用法:
    python scripts/rope_local_to_field.py <project_path> <file_path> <var_name> [--offset <offset>] [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     文件路径（相对于项目根目录）
    var_name      要提升的局部变量名
    --offset      精确定位 offset（0-based），优先于 var_name 的自动定位
    --dry-run     仅预览变更

示例:
    python scripts/rope_local_to_field.py . src/service.py result
    python scripts/rope_local_to_field.py . src/service.py temp_data --offset 342
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.localtofield import LocalToField


def main():
    parser = argparse.ArgumentParser(description="Rope Local to Field")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("var_name", help="要提升的局部变量名")
    parser.add_argument("--offset", type=int, help="精确定位 offset（0-based）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        source = resource.read()

        try:
            offset = (
                args.offset
                if args.offset is not None
                else find_name_offset(source, args.var_name)
            )
        except ValueError as e:
            print(f"❌ {e}")
            return

        try:
            converter = LocalToField(project, resource, offset)
            changes = converter.get_changes()
        except Exception as e:
            msg = str(e)
            if (
                "not inside a class" in msg.lower()
                or "not a local variable" in msg.lower()
            ):
                print(f"❌ '{args.var_name}' 不在类方法上下文中")
                print(
                    "   LocalToField 仅适用于类方法内的局部变量（将其提升为 self.xxx）"
                )
                print("   确保 offset 指向类方法体内的局部变量赋值处")
                return
            if "AttributeError" in type(e).__name__ or "'NoneType'" in msg:
                print(f"❌ Rope 无法解析 '{args.var_name}' 的上下文")
                print("   确保变量在类的实例方法内，且用 --offset 精确定位")
                return
            raise

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(
                f"\n✅ Converted local '{args.var_name}' to field 'self.{args.var_name}'"
            )
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
