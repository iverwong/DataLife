#!/usr/bin/env python3
"""Rope Find Occurrences: 查找符号在项目中的所有出现。

用法:
    python scripts/rope_find_occurrences.py <project_path> <file_path> <name> [--offset N] [--unsure]

示例:
    python scripts/rope_find_occurrences.py . src/models.py MyClass
    python scripts/rope_find_occurrences.py . src/models.py MyClass --offset 42 --unsure
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.contrib.findit import find_occurrences


def main():
    parser = argparse.ArgumentParser(description="Rope Find Occurrences")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("name", help="要查找的符号名")
    parser.add_argument("--unsure", action="store_true", help="包含不确定的匹配")
    parser.add_argument(
        "--offset", type=int, help="精确定位 offset（0-based），优先于 name 的自动定位"
    )
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
        except ValueError:
            print(f"❌ Symbol '{args.name}' not found")
            return

        occurrences = find_occurrences(
            project,
            resource,
            offset,
            unsure=args.unsure,
        )

        print(f"Found {len(occurrences)} occurrence(s) of '{args.name}':\n")
        for occ in occurrences:
            res = occ.resource
            lineno = occ.lineno
            src_lines = res.read().splitlines()
            line_text = (
                src_lines[lineno - 1].strip() if lineno <= len(src_lines) else ""
            )
            unsure_tag = " [unsure]" if occ.unsure else ""
            print(f"  {res.path}:{lineno}  {line_text}{unsure_tag}")


if __name__ == "__main__":
    main()
