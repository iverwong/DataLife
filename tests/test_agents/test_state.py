"""AgentState 和 TodoItem Pydantic 模型测试。

覆盖范围：模型创建、默认值、类型校验、Literal 约束。
无外部依赖。
"""

from __future__ import annotations

import pytest

from core.agents.base import AgentState, TodoItem

class TestTodoItem:
    """TodoItem 模型测试。

    覆盖范围：默认值、完整创建、非法状态值。
    """

    def test_create_with_defaults(self):
        """Given: 仅传入 task
        When: 创建 TodoItem
        Then: status=pending, conclusion=空, added_by=plan"""
        item = TodoItem(task="搜索年报")
        assert item.task == "搜索年报"
        assert item.status == "pending"
        assert item.context == ""
        assert item.conclusion == ""
        assert item.added_by == "plan"

    def test_create_full(self):
        """Given: 传入所有字段
        When: 创建 TodoItem
        Then: 各字段正确赋值"""
        item = TodoItem(
            task="搜索年报",
            context="用户问Q1公告",
            status="done",
            conclusion="找到2条",
            added_by="evaluate",
        )
        assert item.task == "搜索年报"
        assert item.status == "done"
        assert item.added_by == "evaluate"

    def test_invalid_status_raises(self):
        """Given: status 传入非法值 'invalid'
        When: 创建 TodoItem
        Then: 抛出 ValidationError"""
        with pytest.raises(Exception):
            _ = TodoItem(task="x", status="invalid")  # pyright: ignore[reportArgumentType]

    def test_invalid_added_by_raises(self):
        """Given: added_by 传入非法值 'research'
        When: 创建 TodoItem
        Then: 抛出 ValidationError"""
        with pytest.raises(Exception):
            _ = TodoItem(task="x", added_by="research")  # pyright: ignore[reportArgumentType]

class TestAgentState:
    """AgentState 模型测试。

    覆盖范围：最小创建、默认值、必填字段校验。
    """

    def test_minimal_creation(self):
        """Given: 仅传入 question
        When: 创建 AgentState
        Then: 所有可选字段为默认值"""
        state = AgentState(question="贵州茅台Q1公告")
        assert state.question == "贵州茅台Q1公告"
        assert state.todos == []
        assert state.messages == []
        assert state.notes == ""
        assert state.announcements_seen == []
        assert state.iteration == 0
        assert state.total_tokens == 0

    def test_missing_question_raises(self):
        """Given: 未传入 question
        When: 创建 AgentState
        Then: 抛出 ValidationError"""
        with pytest.raises(Exception):
            _ = AgentState()  # pyright: ignore[reportCallIssue]

    def test_with_todos(self):
        """Given: 传入 question + todos
        When: 创建 AgentState
        Then: todos 列表正确赋值"""
        todos = [
            TodoItem(task="搜索年报"),
            TodoItem(task="查找分红公告", context="补充信息"),
        ]
        state = AgentState(question="test", todos=todos)
        assert len(state.todos) == 2
        assert state.todos[0].task == "搜索年报"
