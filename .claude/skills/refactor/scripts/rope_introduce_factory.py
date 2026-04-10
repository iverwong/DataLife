#!/usr/bin/env python3
"""Rope Introduce Factory: 为类引入工厂方法，替换直接构造调用。

用法:
    python scripts/rope_introduce_factory.py <project_path> <file_path> <class_name> <factory_name> [--global] [--offset N] [--dry-run]

参数:
    project_path   项目根目录路径
    file_path      包含目标类的文件路径（相对于项目根目录）
    class_name     目标类名
    factory_name   工厂方法名称
    --global       创建为模块级函数而非 @staticmethod（默认创建 staticmethod）
    --offset       精确定位 offset（0-based），优先于 class_name 的自动定位
    --dry-run      仅预览变更

示例:
    python scripts/rope_introduce_factory.py . src/models.py User create_user
    python scripts/rope_introduce_factory.py . src/models.py Config make_config --global
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.introduce_factory import IntroduceFactory


def main():
    parser = argparse.ArgumentParser(description="Rope Introduce Factory")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("class_name", help="目标类名")
    parser.add_argument("factory_name", help="工厂方法名称")
    parser.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="创建为模块级函数（默认 staticmethod）",
    )
    parser.add_argument(
        "--offset",
        type=int,
        help="精确定位 offset（0-based），优先于 class_name 的自动定位",
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
                else find_name_offset(source, args.class_name)
            )
        except ValueError as e:
            print(f"❌ {e}")
            return

        factory = IntroduceFactory(project, resource, offset)
        changes = factory.get_changes(args.factory_name, global_factory=args.global_)

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(
                f"\n✅ Introduced factory '{args.factory_name}' for class '{args.class_name}'"
            )
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
