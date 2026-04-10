#!/usr/bin/env python3
"""Rope Encapsulate Field: 为类字段生成 getter/setter，自动更新所有引用。

用法:
    python scripts/rope_encapsulate_field.py <project_path> <file_path> <field_name> [--offset N] [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     包含目标字段的文件路径（相对于项目根目录）
    field_name    要封装的字段名（如 my_attr）
    --dry-run     仅预览变更

示例:
    python scripts/rope_encapsulate_field.py . src/models.py name
    python scripts/rope_encapsulate_field.py . src/config.py timeout --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.encapsulate_field import EncapsulateField


def main():
    parser = argparse.ArgumentParser(description="Rope Encapsulate Field")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("field_name", help="要封装的字段名")
    parser.add_argument(
        "--offset",
        type=int,
        help="精确定位 offset（0-based），优先于 field_name 的自动定位",
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
                else find_name_offset(source, args.field_name)
            )
        except ValueError as e:
            print(f"❌ {e}")
            return

        try:
            encapsulator = EncapsulateField(project, resource, offset)
            changes = encapsulator.get_changes()
        except TypeError as e:
            if "'NoneType'" in str(e):
                print(f"❌ Rope 无法解析字段 '{args.field_name}' 的定义上下文")
                print("   可能原因：字段定义在项目外部，或 offset 未指向类实例属性")
                print(f"   建议：用 --offset 精确指向 self.{args.field_name} 的赋值处")
                return
            raise
        except AttributeError as e:
            if "'NoneType'" in str(e):
                print(f"❌ Rope 无法读取字段 '{args.field_name}' 的源码上下文")
                print("   建议：确认字段是类实例属性（self.xxx），且定义在项目内")
                return
            raise

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(
                f"\n✅ Encapsulated field '{args.field_name}' (getter/setter generated)"
            )
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
