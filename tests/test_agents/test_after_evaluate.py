"""条件边 after_evaluate 测试。

覆盖范围：迭代上限、token 上限、有 pending todo、全部完成、空 todo。
无外部依赖，纯逻辑测试。
"""

from core.agents.announcement_analyst import after_evaluate
from core.agents.base import (
    MAX_ITERATIONS,
    MAX_TOKENS,
    AgentState,
    TodoItem,
)

class TestAfterEvaluate:
    """after_evaluate 条件边路由测试。

    覆盖所有分支路径，确保优先级正确：
    迭代上限 > token 上限 > pending todo > synthesize。
    """

    def test_max_iterations_forces_synthesize(self):
        """Given: iteration >= MAX_ITERATIONS，还有 pending todo
        When: 调用 after_evaluate
        Then: 返回 'synthesize'（强制结束）"""
        state = AgentState(
            question="test",
            iteration=MAX_ITERATIONS,
            todos=[TodoItem(task="pending", status="pending")],
        )
        assert after_evaluate(state) == "synthesize"

    def test_max_tokens_forces_synthesize(self):
        """Given: total_tokens >= MAX_TOKENS，还有 pending todo
        When: 调用 after_evaluate
        Then: 返回 'synthesize'（强制结束）"""
        state = AgentState(
            question="test",
            total_tokens=MAX_TOKENS,
            todos=[TodoItem(task="pending", status="pending")],
        )
        assert after_evaluate(state) == "synthesize"

    def test_pending_todos_continue_research(self):
        """Given: 未超限，存在 pending todo
        When: 调用 after_evaluate
        Then: 返回 'research'（继续执行）"""
        state = AgentState(
            question="test",
            iteration=1,
            todos=[
                TodoItem(task="done_task", status="done"),
                TodoItem(task="pending_task", status="pending"),
            ],
        )
        assert after_evaluate(state) == "research"

    def test_all_todos_completed_synthesize(self):
        """Given: 未超限，所有 todo 都是 done/skipped
        When: 调用 after_evaluate
        Then: 返回 'synthesize'"""
        state = AgentState(
            question="test",
            iteration=3,
            todos=[
                TodoItem(task="t1", status="done"),
                TodoItem(task="t2", status="skipped"),
            ],
        )
        assert after_evaluate(state) == "synthesize"

    def test_empty_todos_synthesize(self):
        """Given: 未超限，todo 列表为空
        When: 调用 after_evaluate
        Then: 返回 'synthesize'"""
        state = AgentState(question="test", iteration=1)
        assert after_evaluate(state) == "synthesize"

    def test_iteration_priority_over_pending(self):
        """Given: iteration 刚好等于 MAX_ITERATIONS，有 pending
        When: 调用 after_evaluate
        Then: 迭代上限优先，返回 'synthesize'"""
        state = AgentState(
            question="test",
            iteration=MAX_ITERATIONS,
            total_tokens=0,
            todos=[TodoItem(task="x", status="pending")],
        )
        assert after_evaluate(state) == "synthesize"
