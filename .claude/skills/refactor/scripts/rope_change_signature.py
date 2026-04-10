#!/usr/bin/env python3
"""Rope Change Signature: 修改函数签名（增删重排参数）。

用法:
    python scripts/rope_change_signature.py <project_path> <file_path> <func_name> <action> [options] [--dry-run]

动作:
    add       添加参数：--param <name> [--default <value>] [--index <pos>]
    remove    移除参数：--param <name>
    reorder   重排参数：--order <idx0,idx1,...> [--autodef <value>]

参数:
    project_path  项目根目录路径
    file_path     文件路径（相对于项目根目录）
    func_name     目标函数名
    --dry-run     仅预览变更

示例:
    python scripts/rope_change_signature.py . src/api.py create_user add --param role --default '"admin"' --index 2
    python scripts/rope_change_signature.py . src/api.py create_user remove --param deprecated_flag
    python scripts/rope_change_signature.py . src/api.py create_user reorder --order 0,2,1 --autodef None
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_name_offset, rope_project
from rope.base import libutils
from rope.refactor.change_signature import (
    ArgumentAdder,
    ArgumentRemover,
    ArgumentReorderer,
    ChangeSignature,
)


def main():
    parser = argparse.ArgumentParser(description="Rope Change Signature")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("file_path", help="文件路径（相对于项目根目录）")
    parser.add_argument("func_name", help="目标函数名")
    parser.add_argument("action", choices=["add", "remove", "reorder"], help="操作类型")
    parser.add_argument(
        "--offset",
        type=int,
        help="精确定位 offset（0-based），优先于 func_name 的自动定位",
    )
    parser.add_argument("--param", help="参数名（add/remove 时必需）")
    parser.add_argument("--default", help="默认值（add 时可选）")
    parser.add_argument("--index", type=int, help="插入位置（add 时可选，0-based）")
    parser.add_argument("--order", help="新参数顺序，逗号分隔的索引（reorder 时必需）")
    parser.add_argument("--autodef", help="自动默认值（reorder 时可选）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    with rope_project(args.project_path) as project:
        resource = libutils.path_to_resource(project, args.file_path)
        source = resource.read()

        try:
            offset = (
                args.offset
                if args.offset is not None
                else find_name_offset(source, args.func_name)
            )
        except ValueError as e:
            print(f"❌ {e}")
            return

        changer = ChangeSignature(project, resource, offset)

        if args.action == "add":
            if not args.param:
                parser.error("--param is required for 'add'")
            sig = changer.get_args()
            idx = args.index if args.index is not None else len(sig)
            changers = [ArgumentAdder(idx, args.param, args.default)]

        elif args.action == "remove":
            if not args.param:
                parser.error("--param is required for 'remove'")
            sig = changer.get_args()
            idx = next((i for i, a in enumerate(sig) if a.name == args.param), None)
            if idx is None:
                print(f"❌ Parameter '{args.param}' not found in signature")
                return
            changers = [ArgumentRemover(idx)]

        elif args.action == "reorder":
            if not args.order:
                parser.error("--order is required for 'reorder'")
            new_order = [int(x.strip()) for x in args.order.split(",")]
            changers = [ArgumentReorderer(new_order, autodef=args.autodef)]

        changes = changer.get_changes(changers)
        print(changes.get_description())

        if not args.dry_run:
            project.do(changes)
            print(f"\n✅ Signature of '{args.func_name}' changed ({args.action})")
            print(
                f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
            )
        else:
            print("\n🔍 Dry run — no changes applied")


if __name__ == "__main__":
    main()
