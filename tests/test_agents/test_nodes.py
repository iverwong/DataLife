"""节点函数测试。

覆盖范围：plan, research, evaluate, synthesize 的编排逻辑。
外部依赖全部 mock：BaseChatModel。
计划 3/N 实现节点后补充测试 body。
"""

import pytest


class TestPlanNode:
    """plan 节点测试。

    覆盖范围：初始 todo 创建、task/context 完整性。
    外部依赖 mock：BaseChatModel。
    """

    @pytest.mark.asyncio
    async def test_creates_initial_todos(self):
        """Given: question = '贵州茅台2026Q1重大公告'
        When: 调用 plan
        Then: 返回 3~5 个 pending 的 TodoItem"""

    @pytest.mark.asyncio
    async def test_todos_have_task_and_context(self):
        """Given: 正常 question
        When: 调用 plan
        Then: 每个 TodoItem 的 task 和 context 非空"""


class TestResearchNode:
    """research 节点测试。

    覆盖范围：pending todo 执行、tool 调用、messages 收集、无 pending 时 noop。
    外部依赖 mock：BaseChatModel（含 tool_calls 响应）。
    """

    @pytest.mark.asyncio
    async def test_executes_first_pending_todo(self):
        """Given: todos 有 1 个 done + 1 个 pending
        When: 调用 research
        Then: pending 的 todo 变为 done 或 skipped，conclusion 非空"""

    @pytest.mark.asyncio
    async def test_calls_tools_and_collects_messages(self):
        """Given: LLM 返回 tool_call
        When: 调用 research
        Then: messages 包含 AI + Tool 消息对"""

    @pytest.mark.asyncio
    async def test_no_pending_todo_noop(self):
        """Given: 没有 pending todo
        When: 调用 research
        Then: state 无变化"""


class TestEvaluateNode:
    """evaluate 节点测试。

    覆盖范围：笔记提炼、messages 清空、新增 todo、iteration 递增。
    外部依赖 mock：BaseChatModel。
    """

    @pytest.mark.asyncio
    async def test_extracts_notes(self):
        """Given: messages 中有工具调用结果
        When: 调用 evaluate
        Then: notes 被追加本轮摘要"""

    @pytest.mark.asyncio
    async def test_clears_messages(self):
        """Given: messages 非空
        When: 调用 evaluate
        Then: messages 被清空（返回 Overwrite([])）"""

    @pytest.mark.asyncio
    async def test_can_add_new_todos(self):
        """Given: LLM 判断需补充调研
        When: 调用 evaluate
        Then: todos 新增 ≤2 个 pending 项，added_by='evaluate'"""

    @pytest.mark.asyncio
    async def test_increments_iteration(self):
        """Given: iteration=2
        When: 调用 evaluate
        Then: iteration=3"""


class TestSynthesizeNode:
    """synthesize 节点测试。

    覆盖范围：最终报告生成、skipped 信息包含。
    外部依赖 mock：BaseChatModel。
    """

    @pytest.mark.asyncio
    async def test_generates_final_report(self):
        """Given: todos 有 done/skipped 项 + notes 非空
        When: 调用 synthesize
        Then: notes 更新为最终分析文本"""

    @pytest.mark.asyncio
    async def test_includes_skipped_info(self):
        """Given: 有 skipped todo（结论为'未找到相关公告'）
        When: 调用 synthesize
        Then: 最终报告中体现未找到的信息"""
