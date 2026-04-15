"""结构化输出 Schema 测试。

覆盖范围：PlanOutput、EvaluateOutput 的创建、校验、边界条件。
无外部依赖。
"""

from __future__ import annotations

import pytest

from core.agents.schemas import (
    EvaluateNewTodo,
    EvaluateOutput,
    EvaluateSkipTodo,
    PlanOutput,
    PlanTodo,
)

class TestPlanOutput:
    """PlanOutput Schema 测试。

    覆盖范围：正常创建、空列表校验、字段完整性。
    """

    def test_create_valid(self):
        """Given: 3 个有效 PlanTodo
        When: 创建 PlanOutput
        Then: todos 列表正确赋值"""
        output = PlanOutput(
            todos=[
                PlanTodo(task="搜索年报", context="基础信息源"),
                PlanTodo(task="搜索分红公告", context="补充信息"),
                PlanTodo(task="查找股权激励", context="治理信息"),
            ]
        )
        assert len(output.todos) == 3
        assert output.todos[0].task == "搜索年报"

    def test_empty_todos_raises(self):
        """Given: 空 todos 列表
        When: 创建 PlanOutput
        Then: 抛出 ValidationError（min_length=1）"""
        with pytest.raises(Exception):
            _ = PlanOutput(todos=[])

    def test_max_todos_limit(self):
        """Given: 超过 8 个 todo
        When: 创建 PlanOutput
        Then: 抛出 ValidationError（max_length=8）"""
        todos = [PlanTodo(task=f"task_{i}", context="ctx") for i in range(9)]
        with pytest.raises(Exception):
            _ = PlanOutput(todos=todos)

class TestEvaluateOutput:
    """EvaluateOutput Schema 测试。

    覆盖范围：正常创建、默认值、new_todos 上限、字段完整性。
    """

    def test_create_minimal(self):
        """Given: 仅传入 notes_update
        When: 创建 EvaluateOutput
        Then: new_todos 和 todos_to_skip 为空列表"""
        output = EvaluateOutput(notes_update="发现营收同比增长15%")
        assert output.notes_update == "发现营收同比增长15%"
        assert output.new_todos == []
        assert output.todos_to_skip == []

    def test_create_full(self):
        """Given: 传入所有字段
        When: 创建 EvaluateOutput
        Then: 各字段正确赋值"""
        output = EvaluateOutput(
            notes_update="关键发现",
            new_todos=[
                EvaluateNewTodo(task="补充搜索", context="信息缺口"),
            ],
            todos_to_skip=[
                EvaluateSkipTodo(task="搜索债券", reason="与问题无关"),
            ],
        )
        assert len(output.new_todos) == 1
        assert len(output.todos_to_skip) == 1

    def test_new_todos_max_two(self):
        """Given: 3 个 new_todos
        When: 创建 EvaluateOutput
        Then: 抛出 ValidationError（max_length=2）"""
        with pytest.raises(Exception):
            _ = EvaluateOutput(
                notes_update="x",
                new_todos=[
                    EvaluateNewTodo(task=f"t{i}", context="c")
                    for i in range(3)
                ],
            )
