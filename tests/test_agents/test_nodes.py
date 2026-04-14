"""节点函数测试。

覆盖范围：plan, research, evaluate, synthesize 的编排逻辑。
外部依赖全部 mock：BaseChatModel、tools。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from core.agents.announcement_analyst import (
    evaluate,
    plan,
    research,
    synthesize,
    _apply_evaluate_output,
    _execute_tool_calls,
    _extract_conclusion,
    _extract_tokens,
    _find_first_pending,
    _mark_todo_done,
)
from core.agents.base import AgentState, TodoItem
from core.agents.schemas import (
    EvaluateNewTodo,
    EvaluateOutput,
    EvaluateSkipTodo,
    PlanOutput,
    PlanTodo,
)

# ── 测试工具函数 ─────────────────────────────────────

def _make_ai_message(
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    total_tokens: int = 100,
) -> AIMessage:
    """创建带 usage_metadata 的 AIMessage。"""
    msg = AIMessage(content=content, tool_calls=tool_calls or [])
    msg.usage_metadata = {
        "input_tokens": total_tokens // 2,
        "output_tokens": total_tokens // 2,
        "total_tokens": total_tokens,
    }
    return msg

def _make_structured_result(
    parsed: Any, total_tokens: int = 150
) -> dict[str, Any]:
    """创建 with_structured_output(include_raw=True) 的返回值。"""
    return {
        "raw": _make_ai_message(total_tokens=total_tokens),
        "parsed": parsed,
        "parsing_error": None,
    }

def _mock_structured_model(parsed: Any, total_tokens: int = 150) -> MagicMock:
    """创建 mock model，其 with_structured_output 返回可 ainvoke 的 mock。"""
    mock_model = MagicMock()
    mock_runnable = AsyncMock()
    mock_runnable.ainvoke.return_value = _make_structured_result(
        parsed, total_tokens
    )
    mock_model.with_structured_output.return_value = mock_runnable
    return mock_model

# ── 辅助函数测试 ─────────────────────────────────────

class TestExtractTokens:
    """_extract_tokens 辅助函数测试。"""

    def test_normal(self):
        """Given: AIMessage 有 usage_metadata
        When: 调用 _extract_tokens
        Then: 返回 total_tokens"""
        msg = _make_ai_message(total_tokens=200)
        assert _extract_tokens(msg) == 200

    def test_none_metadata(self):
        """Given: AIMessage 无 usage_metadata
        When: 调用 _extract_tokens
        Then: 返回 0"""
        msg = AIMessage(content="test")
        msg.usage_metadata = None
        assert _extract_tokens(msg) == 0

class TestFindFirstPending:
    """_find_first_pending 辅助函数测试。"""

    def test_found(self):
        """Given: 第二个 todo 是 pending
        When: 调用 _find_first_pending
        Then: 返回 (1, todo)"""
        todos = [
            TodoItem(task="t1", status="done"),
            TodoItem(task="t2", status="pending"),
        ]
        result = _find_first_pending(todos)
        assert result is not None
        assert result[0] == 1
        assert result[1].task == "t2"

    def test_none(self):
        """Given: 无 pending todo
        When: 调用 _find_first_pending
        Then: 返回 None"""
        todos = [TodoItem(task="t1", status="done")]
        assert _find_first_pending(todos) is None

class TestExtractConclusion:
    """_extract_conclusion 辅助函数测试。"""

    def test_last_ai_message(self):
        """Given: 消息列表最后是 AIMessage
        When: 调用 _extract_conclusion
        Then: 返回其 content"""
        msgs: list[AnyMessage] = [
            _make_ai_message(content="中间结果"),
            ToolMessage(content="tool result", tool_call_id="1"),
            _make_ai_message(content="最终结论"),
        ]
        assert _extract_conclusion(msgs) == "最终结论"

    def test_empty_messages(self):
        """Given: 空消息列表
        When: 调用 _extract_conclusion
        Then: 返回默认值"""
        assert _extract_conclusion([]) == "未能得出结论"

class TestMarkTodoDone:
    """_mark_todo_done 辅助函数测试。"""

    def test_marks_done(self):
        """Given: todos 列表和目标索引
        When: 调用 _mark_todo_done
        Then: 目标 todo 变为 done + conclusion，其他不变"""
        todos = [
            TodoItem(task="t1", status="done"),
            TodoItem(task="t2", status="pending"),
        ]
        result = _mark_todo_done(todos, 1, "找到了")
        assert result[1].status == "done"
        assert result[1].conclusion == "找到了"
        assert result[0].status == "done"  # 不受影响
        assert todos[1].status == "pending"  # 原列表不变

class TestApplyEvaluateOutput:
    """_apply_evaluate_output 辅助函数测试。

    覆盖范围：跳过匹配、新增 todo、上限约束。
    """

    def test_skip_matching_pending(self):
        """Given: todos_to_skip 中的 task 匹配某个 pending todo
        When: 调用 _apply_evaluate_output
        Then: 该 todo 变为 skipped + reason 写入 conclusion"""
        todos = [
            TodoItem(task="搜索年报", status="done", conclusion="已完成"),
            TodoItem(task="搜索债券", status="pending"),
        ]
        output = EvaluateOutput(
            notes_update="x",
            todos_to_skip=[
                EvaluateSkipTodo(task="搜索债券", reason="与问题无关"),
            ],
        )
        result = _apply_evaluate_output(todos, output)
        assert result[1].status == "skipped"
        assert result[1].conclusion == "与问题无关"

    def test_add_new_todos(self):
        """Given: new_todos 有 1 个，当前 3 个 todo
        When: 调用 _apply_evaluate_output
        Then: 列表长度变为 4，新 todo 的 added_by=evaluate"""
        todos = [TodoItem(task=f"t{i}") for i in range(3)]
        output = EvaluateOutput(
            notes_update="x",
            new_todos=[
                EvaluateNewTodo(task="新任务", context="补充"),
            ],
        )
        result = _apply_evaluate_output(todos, output)
        assert len(result) == 4
        assert result[3].task == "新任务"
        assert result[3].added_by == "evaluate"

    def test_max_todos_cap(self):
        """Given: 已有 10 个 todo（达上限），new_todos 有 1 个
        When: 调用 _apply_evaluate_output
        Then: 不新增，列表仍为 10 个"""
        todos = [TodoItem(task=f"t{i}") for i in range(10)]
        output = EvaluateOutput(
            notes_update="x",
            new_todos=[EvaluateNewTodo(task="溢出", context="c")],
        )
        result = _apply_evaluate_output(todos, output)
        assert len(result) == 10

    def test_skip_only_pending(self):
        """Given: todos_to_skip 匹配一个 done 的 todo
        When: 调用 _apply_evaluate_output
        Then: 不影响该 todo（只跳过 pending）"""
        todos = [
            TodoItem(task="已完成任务", status="done", conclusion="c"),
        ]
        output = EvaluateOutput(
            notes_update="x",
            todos_to_skip=[
                EvaluateSkipTodo(task="已完成任务", reason="r"),
            ],
        )
        result = _apply_evaluate_output(todos, output)
        assert result[0].status == "done"

class TestExecuteToolCalls:
    """_execute_tool_calls 辅助函数测试。"""

    @pytest.mark.asyncio
    async def test_executes_and_collects(self):
        """Given: 1 个有效 tool_call
        When: 调用 _execute_tool_calls
        Then: 返回 1 个 ToolMessage + 无 seen_id"""
        mock_tool = AsyncMock()
        mock_tool.name = "search_announcements"
        mock_tool.ainvoke.return_value = "搜索结果"
        tool_calls = [{"name": "search_announcements", "args": {"keyword": "年报", "stock_code": "600519"}, "id": "c1"}]
        msgs, seen = await _execute_tool_calls(tool_calls, {"search_announcements": mock_tool})
        assert len(msgs) == 1
        assert msgs[0].content == "搜索结果"
        assert seen == []

    @pytest.mark.asyncio
    async def test_tracks_announcement_ids(self):
        """Given: grep_announcement tool_call
        When: 调用 _execute_tool_calls
        Then: 返回对应 announcement_id 在 seen 列表中"""
        mock_tool = AsyncMock()
        mock_tool.name = "grep_announcement"
        mock_tool.ainvoke.return_value = "grep结果"
        tool_calls = [{"name": "grep_announcement", "args": {"announcement_id": "ann_001", "pattern": "营收"}, "id": "c2"}]
        msgs, seen = await _execute_tool_calls(tool_calls, {"grep_announcement": mock_tool})
        assert "ann_001" in seen

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Given: tool_call 引用不存在的工具
        When: 调用 _execute_tool_calls
        Then: 返回错误提示的 ToolMessage"""
        tool_calls = [{"name": "unknown", "args": {}, "id": "c3"}]
        msgs, seen = await _execute_tool_calls(tool_calls, {})
        assert "未知工具" in msgs[0].content

    @pytest.mark.asyncio
    async def test_tool_exception(self):
        """Given: tool 执行抛出异常
        When: 调用 _execute_tool_calls
        Then: 返回包含错误信息的 ToolMessage（不中断）"""
        mock_tool = AsyncMock()
        mock_tool.name = "search_announcements"
        mock_tool.ainvoke.side_effect = RuntimeError("API 超时")
        tool_calls = [{"name": "search_announcements", "args": {}, "id": "c4"}]
        msgs, seen = await _execute_tool_calls(tool_calls, {"search_announcements": mock_tool})
        assert "工具执行出错" in msgs[0].content

# ── 节点函数测试 ─────────────────────────────────────

class TestPlanNode:
    """plan 节点测试。

    覆盖范围：初始 todo 创建、task/context 完整性、token 计数。
    外部依赖 mock：BaseChatModel（with_structured_output）。
    """

    @pytest.mark.asyncio
    async def test_creates_initial_todos(self):
        """Given: question = '贵州茅台2026Q1重大公告'
        When: 调用 plan
        Then: 返回 3 个 pending 的 TodoItem"""
        parsed = PlanOutput(
            todos=[
                PlanTodo(task="搜索年报", context="基础"),
                PlanTodo(task="搜索分红", context="补充"),
                PlanTodo(task="查找激励", context="治理"),
            ]
        )
        mock_model = _mock_structured_model(parsed, total_tokens=200)
        state = AgentState(question="贵州茅台2026Q1重大公告")
        result = await plan(state, mock_model)
        assert len(result["todos"]) == 3
        assert all(t.status == "pending" for t in result["todos"])
        assert all(t.added_by == "plan" for t in result["todos"])

    @pytest.mark.asyncio
    async def test_todos_have_task_and_context(self):
        """Given: 正常 question
        When: 调用 plan
        Then: 每个 TodoItem 的 task 和 context 非空"""
        parsed = PlanOutput(
            todos=[PlanTodo(task="搜索年报", context="基础信息源")]
        )
        mock_model = _mock_structured_model(parsed)
        state = AgentState(question="test")
        result = await plan(state, mock_model)
        for todo in result["todos"]:
            assert todo.task
            assert todo.context

    @pytest.mark.asyncio
    async def test_returns_token_count(self):
        """Given: LLM 消耗 200 tokens
        When: 调用 plan
        Then: total_tokens = 200"""
        parsed = PlanOutput(
            todos=[PlanTodo(task="t", context="c")]
        )
        mock_model = _mock_structured_model(parsed, total_tokens=200)
        state = AgentState(question="test")
        result = await plan(state, mock_model)
        assert result["total_tokens"] == 200

class TestResearchNode:
    """research 节点测试。

    覆盖范围：pending todo 执行、tool 调用、messages 收集、无 pending 时 noop。
    外部依赖 mock：BaseChatModel（含 tool_calls 响应）、tools。
    """

    @pytest.mark.asyncio
    async def test_executes_first_pending_todo(self):
        """Given: todos 有 1 个 done + 1 个 pending，LLM 无 tool_calls
        When: 调用 research
        Then: pending 的 todo 变为 done，conclusion 非空"""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = _make_ai_message(
            content="年报营收1850亿", total_tokens=300
        )
        state = AgentState(
            question="test",
            todos=[
                TodoItem(task="done_task", status="done", conclusion="c"),
                TodoItem(task="搜索年报", status="pending"),
            ],
        )
        result = await research(state, mock_model, [])
        assert result["todos"][1].status == "done"
        assert result["todos"][1].conclusion == "年报营收1850亿"

    @pytest.mark.asyncio
    async def test_calls_tools_and_collects_messages(self):
        """Given: LLM 先返回 tool_call，再返回纯文本
        When: 调用 research
        Then: messages 包含 AI + Tool + AI 消息"""
        # 第一次调用：返回 tool_call
        ai_with_tc = _make_ai_message(
            content="",
            tool_calls=[{"name": "search_announcements", "args": {"keyword": "年报", "stock_code": "600519"}, "id": "c1"}],
            total_tokens=100,
        )
        # 第二次调用：返回纯文本（结束循环）
        ai_final = _make_ai_message(content="总结", total_tokens=80)
        mock_model = AsyncMock()
        mock_model.ainvoke.side_effect = [ai_with_tc, ai_final]

        mock_tool = AsyncMock()
        mock_tool.name = "search_announcements"
        mock_tool.ainvoke.return_value = "搜索结果"

        state = AgentState(
            question="test",
            todos=[TodoItem(task="搜索年报", status="pending")],
        )
        result = await research(state, mock_model, [mock_tool])
        assert len(result["messages"]) == 3  # AI(tc) + Tool + AI(final)
        assert result["total_tokens"] == 180

    @pytest.mark.asyncio
    async def test_no_pending_todo_noop(self):
        """Given: 没有 pending todo
        When: 调用 research
        Then: 返回空 dict"""
        state = AgentState(
            question="test",
            todos=[TodoItem(task="t", status="done", conclusion="c")],
        )
        result = await research(state, AsyncMock(), [])
        assert result == {}

class TestEvaluateNode:
    """evaluate 节点测试。

    覆盖范围：笔记提炼、messages 清空、新增 todo、iteration 递增。
    外部依赖 mock：BaseChatModel（with_structured_output）。
    """

    @pytest.mark.asyncio
    async def test_extracts_notes(self):
        """Given: LLM 返回 notes_update
        When: 调用 evaluate
        Then: notes 被追加"""
        parsed = EvaluateOutput(notes_update="营收同比增长15%")
        mock_model = _mock_structured_model(parsed)
        state = AgentState(
            question="test",
            notes="前轮发现",
            todos=[TodoItem(task="t", status="done", conclusion="c")],
            messages=[_make_ai_message(content="调研过程")],
        )
        result = await evaluate(state, mock_model)
        assert "营收同比增长15%" in result["notes"]
        assert "前轮发现" in result["notes"]

    @pytest.mark.asyncio
    async def test_clears_messages(self):
        """Given: messages 非空
        When: 调用 evaluate
        Then: messages 被 Overwrite 清空"""
        parsed = EvaluateOutput(notes_update="x")
        mock_model = _mock_structured_model(parsed)
        state = AgentState(
            question="test",
            messages=[_make_ai_message(content="msg")],
        )
        result = await evaluate(state, mock_model)
        # Overwrite([]) 的值应为空列表（通过 Overwrite 包装）
        from langgraph.types import Overwrite as OverwriteType
        assert isinstance(result["messages"], OverwriteType)

    @pytest.mark.asyncio
    async def test_can_add_new_todos(self):
        """Given: LLM 判断需补充调研
        When: 调用 evaluate
        Then: todos 新增项，added_by='evaluate'"""
        parsed = EvaluateOutput(
            notes_update="x",
            new_todos=[EvaluateNewTodo(task="补充搜索", context="缺口")],
        )
        mock_model = _mock_structured_model(parsed)
        state = AgentState(
            question="test",
            todos=[TodoItem(task="t", status="done", conclusion="c")],
        )
        result = await evaluate(state, mock_model)
        assert len(result["todos"]) == 2
        assert result["todos"][1].added_by == "evaluate"

    @pytest.mark.asyncio
    async def test_increments_iteration(self):
        """Given: iteration=2
        When: 调用 evaluate
        Then: iteration=3"""
        parsed = EvaluateOutput(notes_update="x")
        mock_model = _mock_structured_model(parsed)
        state = AgentState(question="test", iteration=2)
        result = await evaluate(state, mock_model)
        assert result["iteration"] == 3

class TestSynthesizeNode:
    """synthesize 节点测试。

    覆盖范围：最终报告生成、token 计数。
    外部依赖 mock：BaseChatModel。
    """

    @pytest.mark.asyncio
    async def test_generates_final_report(self):
        """Given: todos 有 done/skipped 项 + notes 非空
        When: 调用 synthesize
        Then: notes 更新为最终分析文本"""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = _make_ai_message(
            content="# 分析报告\n\n营收增长15%...", total_tokens=500
        )
        state = AgentState(
            question="test",
            todos=[
                TodoItem(task="t1", status="done", conclusion="c1"),
                TodoItem(task="t2", status="skipped", conclusion="未找到"),
            ],
            notes="前期笔记",
        )
        result = await synthesize(state, mock_model)
        assert "分析报告" in result["notes"]
        assert result["total_tokens"] == 500

    @pytest.mark.asyncio
    async def test_includes_skipped_info(self):
        """Given: 有 skipped todo
        When: 调用 synthesize
        Then: LLM 收到的 prompt 中包含 skipped 任务信息"""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = _make_ai_message(content="报告")
        state = AgentState(
            question="test",
            todos=[
                TodoItem(task="查找激励", status="skipped", conclusion="未找到相关公告"),
            ],
            notes="",
        )
        _ = await synthesize(state, mock_model)
        # 验证传给 LLM 的消息中包含 skipped 任务
        call_args = mock_model.ainvoke.call_args[0][0]
        prompt_text = str(call_args)
        assert "查找激励" in prompt_text
        assert "skipped" in prompt_text or "未找到" in prompt_text
