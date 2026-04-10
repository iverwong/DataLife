#!/usr/bin/env python3
"""Rope Restructure: 基于模式匹配的批量代码转换。

用法:
    python scripts/rope_restructure.py <project_path> --pattern <pattern> --goal <goal> [--args <key=value>...] [--dry-run]

参数:
    project_path  项目根目录路径
    --pattern     匹配模式，使用 ${name} 作为通配符
    --goal        替换目标，可引用 ${name}
    --args        通配符约束，格式为 key=value（如 func=name=mod.func）
    --dry-run     仅预览变更

模式语法:
    ${name}     匹配任意表达式
    约束格式:   name=module.symbol   限定符号来源
               type=module.Class    限定类型
               exact                仅匹配精确名称，不匹配别名

示例:
    # 将 pow(x, y) 替换为 x ** y
    python scripts/rope_restructure.py . \
        --pattern '${f}(${x}, ${y})' \
        --goal '${x} ** ${y}' \
        --args 'f=name=mymod.pow'

    # 将 obj.set(val) 替换为 obj = val
    python scripts/rope_restructure.py . \
        --pattern '${x}.set(${y})' \
        --goal '${x} = ${y}' \
        --args 'x=type=mymod.Config'
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import rope_project
from rope.refactor.restructure import Restructure


def parse_args_dict(args_list):
    """解析 key=value 参数为字典。

    partition 只在第一个 '=' 处分割，
    因此 'f=name=mod.func' 正确解析为 key='f', value='name=mod.func'。
    """
    result = {}
    if not args_list:
        return result
    for item in args_list:
        key, _, value = item.partition("=")
        result[key.strip()] = value.strip()
    return result


def main():
    parser = argparse.ArgumentParser(description="Rope Restructure")
    parser.add_argument("project_path", help="项目根目录路径")
    parser.add_argument("--pattern", required=True, help="匹配模式")
    parser.add_argument("--goal", required=True, help="替换目标")
    parser.add_argument("--args", nargs="*", help="通配符约束 key=value")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更")
    args = parser.parse_args()

    wildcard_args = parse_args_dict(args.args)

    with rope_project(args.project_path) as project:
        restructuring = Restructure(project, args.pattern, args.goal, wildcard_args)
        changes = restructuring.get_changes()

        if changes.get_changed_resources():
            print(changes.get_description())
            if not args.dry_run:
                project.do(changes)
                print("\n✅ Restructuring applied")
                print(
                    f"   Changed files: {[r.path for r in changes.get_changed_resources()]}"
                )
            else:
                print("\n🔍 Dry run — no changes applied")
        else:
            print("ℹ️ No matches found for the given pattern")


if __name__ == "__main__":
    main()
