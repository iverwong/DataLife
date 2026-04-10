#!/usr/bin/env python3
"""Rope Method Object: 将方法转为方法对象（类）。

将复杂方法转为独立类，原方法的参数和局部变量变为类的属性，
方法体变为该类的 __call__ 或指定方法。适用于参数过多、
局部变量过多的长方法重构。

用法:
    python scripts/rope_method_object.py <project_path> <file_path> <method_name> <class_name> [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     文件路径（相对于项目根目录）
    method_name   要转换的方法名
    class_name    新类名
    --offset      精确定位 offset（0-based），优先于 method_name 的自动定位
    --dry-run     仅预览变更

示例:
    python scripts/rope_method_object.py . src/processor.py complex_process ProcessorObject
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.method_object import MethodObject


def main():
    parser = argparse.ArgumentParser(description="Rope Method Object")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("method_name", help="要转换的方法名")
    parser.add_argument("class_name", help="新类名")
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
                else find_name_offset(source, args.method_name)
            )
        except ValueError as e:
            print(f"❌ {e}")
            return

        converter = MethodObject(project, resource, offset)
        changes = converter.get_changes(args.class_name)

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(
                f"\n✅ Converted method '{args.method_name}' to class '{args.class_name}'"
            )
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
