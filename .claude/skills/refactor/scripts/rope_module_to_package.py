#!/usr/bin/env python3
"""Rope Module to Package: 将模块文件转为同名包。

将 mod.py 转换为 mod/__init__.py，自动更新所有 import。

用法:
    python scripts/rope_module_to_package.py <project_path> <file_path> [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     模块文件路径（相对于项目根目录）
    --dry-run     仅预览变更

示例:
    python scripts/rope_module_to_package.py . src/utils.py
    python scripts/rope_module_to_package.py . src/large_module.py --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import rope_project
from rope.base import libutils
from rope.refactor.topackage import ModuleToPackage


def main():
    parser = argparse.ArgumentParser(description="Rope Module to Package")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="模块文件路径（相对于项目根目录）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        converter = ModuleToPackage(project, resource)
        changes = converter.get_changes()

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(f"\n✅ Converted '{args.file_path}' to package")
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
