#!/usr/bin/env python3
"""验证生成的测试代码是否符合规范.

用法:
    python validate_tests.py <test_file_path>

示例:
    python validate_tests.py tests/test_data/test_announcement.py
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple


class TestValidator(ast.NodeVisitor):
    """验证测试文件的AST访问器."""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.has_asyncio_mark = False
        self.has_test_class = False
        self.has_docstring = False

    def validate(self) -> Tuple[List[str], List[str]]:
        """执行验证."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except SyntaxError as e:
            self.errors.append(f"语法错误: {e}")
            return self.errors, self.warnings

        self.visit(tree)

        # 检查模块级docstring
        if not self.has_docstring:
            self.warnings.append("缺少模块级docstring")

        return self.errors, self.warnings

    def visit_Module(self, node):
        """访问模块节点."""
        # 检查模块级docstring
        if node.body and isinstance(node.body[0], ast.Expr):
            if isinstance(node.body[0].value, ast.Constant):
                if isinstance(node.body[0].value.value, str):
                    self.has_docstring = True

        # 检查pytestmark
        for child in node.body:
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id == "pytestmark":
                        self.has_asyncio_mark = True

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        """访问类定义."""
        if node.name.startswith("Test"):
            self.has_test_class = True

            # 检查类docstring
            if not ast.get_docstring(node):
                self.warnings.append(f"类 {node.name} 缺少docstring")

            # 检查测试方法
            has_test_method = False
            for item in node.body:
                if isinstance(item, ast.FunctionDef) or isinstance(
                    item, ast.AsyncFunctionDef
                ):
                    if item.name.startswith("test_"):
                        has_test_method = True
                        self._validate_test_method(item)

            if not has_test_method:
                self.errors.append(f"类 {node.name} 没有测试方法")

        self.generic_visit(node)

    def _validate_test_method(self, node):
        """验证测试方法."""
        # 检查方法docstring
        if not ast.get_docstring(node):
            self.warnings.append(f"方法 {node.name} 缺少docstring")

        # 检查是否有测试标记
        has_mark = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr in [
                        "mark",
                        "unit",
                        "integration",
                        "fast",
                        "slow",
                    ]:
                        has_mark = True
            elif isinstance(decorator, ast.Attribute):
                if decorator.attr in ["mark", "unit", "integration", "fast", "slow"]:
                    has_mark = True

        if not has_mark:
            self.warnings.append(f"方法 {node.name} 缺少pytest.mark")

        # 检查异步方法
        if isinstance(node, ast.AsyncFunctionDef):
            if not self.has_asyncio_mark:
                # 检查是否有@ pytest.mark.asyncio
                has_asyncio = False
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Attribute):
                            if decorator.func.attr == "asyncio":
                                has_asyncio = True

                if not has_asyncio:
                    self.errors.append(
                        f"异步方法 {node.name} 缺少@pytest.mark.asyncio或模块级pytestmark"
                    )


def main():
    """主函数."""
    if len(sys.argv) < 2:
        print("用法: python validate_tests.py <test_file_path>")
        sys.exit(1)

    file_path = sys.argv[1]

    if not Path(file_path).exists():
        print(f"错误: 文件不存在 {file_path}")
        sys.exit(1)

    validator = TestValidator(file_path)
    errors, warnings = validator.validate()

    print(f"\n验证文件: {file_path}")
    print("=" * 60)

    if errors:
        print(f"\n❌ 发现 {len(errors)} 个错误:")
        for error in errors:
            print(f"   - {error}")

    if warnings:
        print(f"\n⚠️  发现 {len(warnings)} 个警告:")
        for warning in warnings:
            print(f"   - {warning}")

    if not errors and not warnings:
        print("\n✅ 验证通过！")
    elif not errors:
        print("\n✅ 验证通过（有警告）")
    else:
        print("\n❌ 验证失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
