#!/usr/bin/env python3
"""Rope Extract: 提取方法或变量。

用法:
    # 提取为方法（默认）
    python scripts/rope_extract.py <project_path> <file_path> <start_line> <end_line> <name> [--similar] [--global] [--dry-run]
    # 提取为变量
    python scripts/rope_extract.py <project_path> <file_path> <start_line> <end_line> <name> --variable [--dry-run]

参数:
    project_path  项目根目录路径
    file_path     文件路径（相对于项目根目录）
    start_line    起始行号（1-based）
    end_line      结束行号（1-based，包含）
    name          提取后的方法/变量名（前缀 @ 提取为 classmethod，$ 提取为 staticmethod）
    --variable    提取为变量而非方法（默认提取方法）
    --similar     同时提取相似的代码块
    --global      提取为全局函数/变量
    --dry-run     仅预览变更

示例:
    python scripts/rope_extract.py . src/handler.py 45 60 process_items --similar
    python scripts/rope_extract.py . src/calc.py 10 10 TAX_RATE --variable
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import lines_to_offsets, rope_project
from rope.base import libutils
from rope.refactor.extract import ExtractMethod, ExtractVariable


def main():
    parser = argparse.ArgumentParser(description="Rope Extract")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("start_line", type=int, help="起始行号 (1-based)")
    parser.add_argument("end_line", type=int, help="结束行号 (1-based，包含)")
    parser.add_argument("new_name", help="提取后的方法/变量名")
    parser.add_argument("--variable", action="store_true", help="提取为变量而非方法")
    parser.add_argument("--similar", action="store_true", help="同时提取相似代码块")
    parser.add_argument(
        "--global", dest="global_", action="store_true", help="提取为全局函数/变量"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        source = resource.read()
        start, end = lines_to_offsets(source, args.start_line, args.end_line)

        ExtractClass = ExtractVariable if args.variable else ExtractMethod
        extractor = ExtractClass(project, resource, start, end)
        kwargs = {"similar": args.similar}
        if not args.variable:
            # global_ 仅 ExtractMethod 支持；ExtractVariable 不接受此参数
            kwargs["global_"] = args.global_
        changes = extractor.get_changes(args.new_name, **kwargs)

        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            kind = "variable" if args.variable else "method"
            print(f"\n✅ Extracted {kind} '{args.new_name}'")
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
