"""公告查询 Agent 图组装。

图结构：START → plan → research → evaluate →[条件边]→ synthesize → END
                                      ↑                    │
                                      └── "有 pending" ────┘
"""

from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langgraph.graph import (
    END,
    START,
    StateGraph,
)
from langgraph.graph.state import (
    CompiledStateGraph,
)
from langgraph.types import Overwrite

from core.agents.base import (
    MAX_ITERATIONS,
    MAX_NEW_TODOS_PER_EVAL,
    MAX_TODOS,
    MAX_TOKENS,
    AgentState,
    TodoItem,
)
from core.agents.prompts import (
    EVALUATE_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT,
    RESEARCH_SYSTEM_PROMPT, SYNTHESIZE_SYSTEM_PROMPT,
)
from core.agents.schemas import EvaluateOutput, PlanOutput
from core.tools import ANNOUNCEMENT_TOOLS

# ── 节点逻辑函数 ─────────────────────────────────────


async def plan(state: AgentState, model: BaseChatModel) -> dict[str, Any]:
    """规划节点：分析用户问题，拆解为 3~5 个初始 todo。

    只在首轮执行一次，不参与后续循环。

    Args:
        state: 当前图状态（读取 question）。
        model: LLM 实例。

    Returns:
        状态更新 dict，包含 todos 列表。
    """
    messages = _build_plan_messages(state.question)
    result = await _invoke_structured(model, PlanOutput, messages)
    todos = _parse_plan_todos(result["parsed"])
    return {
        "todos": todos,
        "total_tokens": _extract_tokens(result["raw"]),
    }


async def research(
    state: AgentState,
    model_with_tools: BaseChatModel,
    tools: list[Any],
) -> dict[str, Any]:
    """执行节点：取第一个 pending todo，通过手动 ReAct 循环执行。

    内部循环：构建 prompt → LLM 决定调用 tool → 执行 tool →
    返回结果 → 重复，直到 LLM 不再请求 tool call。

    Args:
        state: 当前图状态（读取 todos, notes, announcements_seen）。
        model_with_tools: 绑定了工具的 LLM 实例。
        tools: 可用工具列表（用于按名称查找执行）。

    Returns:
        状态更新 dict，包含更新后的 todos, messages,
        announcements_seen, total_tokens。
    """
    pending = _find_first_pending(state.todos)
    if pending is None:
        return {}
    idx, todo = pending
    context = _build_research_context(todo, state.notes, state.announcements_seen)
    collected_msgs, new_seen, tokens = await _react_loop(
        model_with_tools, tools, context
    )
    conclusion = _extract_conclusion(collected_msgs)
    updated_todos = _mark_todo_done(state.todos, idx, conclusion)
    return {
        "todos": updated_todos,
        "messages": collected_msgs,
        "announcements_seen": new_seen,
        "total_tokens": tokens,
    }


async def evaluate(state: AgentState, model: BaseChatModel) -> dict[str, Any]:
    """评估节点：提炼本轮笔记，审视 todo 列表，可追加新 todo。

    核心节点，是循环的判断点。每轮执行后：
    - 追加 notes（提炼本轮发现）
    - 清空 messages（为下轮准备干净上下文）
    - 可添加新 todo（≤2 个，仅当发现明确信息缺口时）
    - 可标记 todo 为 skipped
    - iteration + 1

    Args:
        state: 当前图状态（读取 messages, todos, notes）。
        model: LLM 实例。

    Returns:
        状态更新 dict，包含 todos, notes, messages(清空),
        iteration, total_tokens。
    """
    messages = _build_evaluate_messages(state.messages, state.todos, state.notes)
    result = await _invoke_structured(model, EvaluateOutput, messages)
    parsed: EvaluateOutput = result["parsed"]
    updated_todos = _apply_evaluate_output(state.todos, parsed)
    new_notes = (
        state.notes + "\n\n" + parsed.notes_update
        if state.notes
        else parsed.notes_update
    )
    return {
        "todos": updated_todos,
        "notes": new_notes,
        "messages": Overwrite([]),
        "iteration": state.iteration + 1,
        "total_tokens": _extract_tokens(result["raw"]),
    }


async def synthesize(state: AgentState, model: BaseChatModel) -> dict[str, Any]:
    """输出节点：基于 todos + notes 生成最终分析报告。

    Args:
        state: 当前图状态（读取 todos, notes）。
        model: LLM 实例。

    Returns:
        状态更新 dict，包含 notes（最终分析文本）和 total_tokens。
    """
    messages = _build_synthesize_messages(state.todos, state.notes)
    response: AIMessage = await model.ainvoke(messages)
    return {
        "notes": str(response.content),
        "total_tokens": _extract_tokens(response),
    }


# ── 条件边 ───────────────────────────────────────────


def after_evaluate(state: AgentState) -> str:
    """条件边路由：判断 evaluate 后进入 research 还是 synthesize。

    规则（按优先级）：
    1. iteration >= MAX_ITERATIONS → synthesize
    2. total_tokens >= MAX_TOKENS → synthesize
    3. 存在 pending todo → research
    4. 否则 → synthesize
    """
    if state.iteration >= MAX_ITERATIONS:
        return "synthesize"
    if state.total_tokens >= MAX_TOKENS:
        return "synthesize"
    pending = [t for t in state.todos if t.status == "pending"]
    if pending:
        return "research"
    return "synthesize"


# ── 图组装 ───────────────────────────────────────────


def build_announcement_analyst_graph(
    model: BaseChatModel,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """构建公告查询 Agent 的 LangGraph 编译图。

    图结构：START → plan → research → evaluate →[条件边]→ synthesize → END

    Args:
        model: LLM 实例（BaseChatModel），不绑定具体 provider。
            调用方传入任意 langchain chat model 即可。

    Returns:
        编译后的 CompiledStateGraph，通过 ainvoke 调用：
        ``result = await graph.ainvoke({"question": "..."})``
    """
    tools = ANNOUNCEMENT_TOOLS
    model_with_tools = model.bind_tools(tools)  # type: ignore[assignment]

    async def _plan(state: AgentState) -> dict[str, Any]:
        return await plan(state, model)

    async def _research(state: AgentState) -> dict[str, Any]:
        return await research(state, cast(BaseChatModel, model_with_tools), tools)

    async def _evaluate(state: AgentState) -> dict[str, Any]:
        return await evaluate(state, model)

    async def _synthesize(state: AgentState) -> dict[str, Any]:
        return await synthesize(state, model)

    graph = StateGraph(AgentState)

    _ = graph.add_node("plan", _plan)
    _ = graph.add_node("research", _research)
    _ = graph.add_node("evaluate", _evaluate)
    _ = graph.add_node("synthesize", _synthesize)

    _ = graph.add_edge(START, "plan")
    _ = graph.add_edge("plan", "research")
    _ = graph.add_edge("research", "evaluate")
    _ = graph.add_conditional_edges(
        "evaluate",
        after_evaluate,
        {"research": "research", "synthesize": "synthesize"},
    )
    _ = graph.add_edge("synthesize", END)

    return graph.compile()


# ── 共享辅助 ─────────────────────────────────────────


async def _invoke_structured(
    model: BaseChatModel,
    schema: type,
    messages: list[AnyMessage],
) -> dict[str, Any]:
    """调用 LLM 并获取结构化输出 + 原始响应。

    使用 with_structured_output(include_raw=True)，返回：
    {"raw": AIMessage, "parsed": schema 实例, "parsing_error": Exception | None}
    """
    llm_with_structured = model.with_structured_output(schema, include_raw=True)
    return cast(dict[str, Any], await llm_with_structured.ainvoke(messages))


def _extract_tokens(response: AIMessage) -> int:
    """从 AIMessage.usage_metadata 提取 total_tokens。

    若 usage_metadata 为 None，返回 0。
    """
    metadata = response.usage_metadata
    if metadata is None:
        return 0
    return metadata.get("total_tokens", 0)


# ── plan 辅助 ────────────────────────────────────────


def _build_plan_messages(question: str) -> list[AnyMessage]:
    """构建 plan 节点的 LLM 输入消息。

    Returns:
        [SystemMessage(PLAN_SYSTEM_PROMPT), HumanMessage(question)]
    """
    return [
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        HumanMessage(content=question),
    ]


def _parse_plan_todos(parsed: PlanOutput) -> list[TodoItem]:
    """将 PlanOutput 转换为 TodoItem 列表。

    每个 PlanTodo 映射为 TodoItem(task=..., context=..., added_by="plan")。
    """
    return [
        TodoItem(task=t.task, context=t.context, added_by="plan")
        for t in parsed.todos
    ]


# ── research 辅助 ────────────────────────────────────


def _find_first_pending(
    todos: list[TodoItem],
) -> tuple[int, TodoItem] | None:
    """找到第一个 status=pending 的 todo，返回 (索引, TodoItem)。

    无 pending 则返回 None。
    """
    for i, todo in enumerate(todos):
        if todo.status == "pending":
            return i, todo
    return None


def _build_research_context(
    todo: TodoItem, notes: str, announcements_seen: list[str]
) -> str:
    """构建 research 节点的 HumanMessage 内容。

    包含：
    - 当前任务的 task 和 context
    - 已有的分析笔记（供参考，非重复执行）
    - 已查看过的公告 ID（避免重复查看）
    """
    parts = [f"## 当前任务\n- 任务：{todo.task}\n- 背景：{todo.context}"]
    if notes:
        parts.append(f"\n## 已有的分析笔记\n{notes}")
    if announcements_seen:
        seen_str = ", ".join(announcements_seen)
        parts.append(f"\n## 已查看过的公告 ID\n{seen_str}（请勿重复查看）")
    return "\n".join(parts)


def _extract_conclusion(messages: list[AnyMessage]) -> str:
    """从消息列表中提取最后一条 AIMessage 的内容作为结论。

    从后向前搜索，返回第一条有内容的 AIMessage.content。
    若无 AIMessage，返回 '未能得出结论'。
    """
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content)
    return "未能得出结论"


def _mark_todo_done(
    todos: list[TodoItem], idx: int, conclusion: str
) -> list[TodoItem]:
    """标记指定索引的 todo 为 done，写入 conclusion。

    返回新的 todos 列表（不修改原列表）。
    """
    updated = list(todos)
    updated[idx] = updated[idx].model_copy(
        update={"status": "done", "conclusion": conclusion}
    )
    return updated


# ── evaluate 辅助 ────────────────────────────────────


def _build_evaluate_messages(
    messages: list[AnyMessage],
    todos: list[TodoItem],
    notes: str,
) -> list[AnyMessage]:
    """构建 evaluate 节点的 LLM 输入消息。

    包含 SystemMessage + HumanMessage（内含本轮对话摘要、todo 列表、已有笔记）。
    """
    # 将消息列表转换为摘要文本
    msg_summary = _summarize_messages(messages)

    todo_lines = []
    for t in todos:
        status_str = f"[{t.status}]" if t.status != "pending" else "[pending]"
        conclusion_str = f"\n  结论：{t.conclusion}" if t.conclusion else ""
        todo_lines.append(f"- {status_str} {t.task} (来源：{t.added_by}){conclusion_str}")

    todo_text = "\n".join(todo_lines) if todo_lines else "（空）"
    notes_text = f"\n\n## 已有笔记\n{notes}" if notes else ""

    human_content = (
        f"## 本轮对话摘要\n{msg_summary}\n\n"
        f"## 任务列表\n{todo_text}\n"
        f"{notes_text}"
    )

    return [
        SystemMessage(content=EVALUATE_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]


def _summarize_messages(messages: list[AnyMessage]) -> str:
    """将消息列表汇总为可读文本供 evaluate 使用。"""
    if not messages:
        return "（无对话记录）"
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            content = str(m.content)
            lines.append(f"Human: {content[:300]}{'...' if len(content) > 300 else ''}")
        elif isinstance(m, AIMessage):
            if m.tool_calls:
                calls_str = ", ".join(tc["name"] for tc in m.tool_calls)
                lines.append(f"AI (调用工具: {calls_str})")
            else:
                content = str(m.content)
                lines.append(f"AI: {content[:200]}{'...' if len(content) > 200 else ''}")
        elif isinstance(m, ToolMessage):
            content = str(m.content)
            lines.append(f"Tool[{m.tool_call_id}]: {content[:200]}{'...' if len(content) > 200 else ''}")
    return "\n".join(lines)


# ── synthesize 辅助 ──────────────────────────────────


def _build_synthesize_messages(
    todos: list[TodoItem], notes: str
) -> list[AnyMessage]:
    """构建 synthesize 节点的 LLM 输入消息。

    包含 SystemMessage + HumanMessage（内含完整 todo 列表及结论、累积笔记）。
    """
    todo_lines = []
    for t in todos:
        conclusion_str = f"\n  结论：{t.conclusion}" if t.conclusion else ""
        todo_lines.append(
            f"- [{t.status.upper()}] {t.task} (来源：{t.added_by}){conclusion_str}"
        )
    todo_text = "\n".join(todo_lines) if todo_lines else "（空）"

    human_content = (
        f"## 任务列表及结论\n{todo_text}\n\n"
        f"## 累积分析笔记\n{notes if notes else '（无）'}"
    )

    return [
        SystemMessage(content=SYNTHESIZE_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]


# ── research 复杂子函数 ──────────────────────────────

MAX_REACT_STEPS: int = 15
"""单次 research 的 ReAct 循环最大步数。"""


async def _react_loop(
    model_with_tools: BaseChatModel,
    tools: list[Any],
    context: str,
) -> tuple[list[AnyMessage], list[str], int]:
    """手动 ReAct 循环：LLM → tool_calls → execute → repeat。

    Args:
        model_with_tools: 绑定工具的 LLM。
        tools: 工具列表（用于按名称查找执行）。
        context: HumanMessage 内容（任务描述 + 背景）。

    Returns:
        (收集的 AI/Tool 消息列表, 新发现的 announcement_id 列表, 累计 token 数)
    """
    tool_map: dict[str, Any] = {t.name: t for t in tools}
    conversation: list[AnyMessage] = [
        SystemMessage(content=RESEARCH_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]
    collected: list[AnyMessage] = []
    new_seen: list[str] = []
    total_tokens: int = 0

    for _ in range(MAX_REACT_STEPS):
        response: AIMessage = await model_with_tools.ainvoke(conversation)
        collected.append(response)
        conversation.append(response)
        total_tokens += _extract_tokens(response)

        if not response.tool_calls:
            break

        tool_messages, seen_ids = await _execute_tool_calls(
            response.tool_calls, tool_map
        )
        collected.extend(tool_messages)
        conversation.extend(tool_messages)
        new_seen.extend(
            aid for aid in seen_ids if aid not in new_seen
        )

    return collected, new_seen, total_tokens


async def _execute_tool_calls(
    tool_calls: list[Any],
    tool_map: dict[str, Any],
) -> tuple[list[ToolMessage], list[str]]:
    """执行一批 tool call，返回 ToolMessage 列表和新发现的 announcement_id。

    Args:
        tool_calls: AIMessage.tool_calls（list of {"name", "args", "id"}）。
        tool_map: 工具名称 → 工具实例映射。

    Returns:
        (ToolMessage 列表, 本批次涉及的 announcement_id 列表)
    """
    tool_messages: list[ToolMessage] = []
    seen_ids: list[str] = []

    for tc in tool_calls:
        tool = tool_map.get(tc["name"])
        if tool is None:
            tool_messages.append(
                ToolMessage(
                    content=f"未知工具: {tc['name']}",
                    tool_call_id=tc["id"],
                )
            )
            continue
        try:
            result = await tool.ainvoke(tc["args"])
        except Exception as e:
            result = f"工具执行出错: {e}"
        tool_messages.append(
            ToolMessage(content=str(result), tool_call_id=tc["id"])
        )
        # 追踪已查看的公告 ID
        if tc["name"] in ("grep_announcement", "read_announcement"):
            ann_id = tc["args"].get("announcement_id")
            if ann_id and ann_id not in seen_ids:
                seen_ids.append(ann_id)

    return tool_messages, seen_ids


# ── evaluate 复杂子函数 ──────────────────────────────


def _apply_evaluate_output(
    todos: list[TodoItem],
    output: EvaluateOutput,
) -> list[TodoItem]:
    """应用 evaluate 的结构化输出到 todo 列表。

    规则：
    1. 将 todos_to_skip 中匹配的 pending todo 标记为 skipped
    2. 新增 new_todos（受 MAX_NEW_TODOS_PER_EVAL 和 MAX_TODOS 约束）

    Args:
        todos: 当前 todo 列表。
        output: evaluate 的结构化输出。

    Returns:
        更新后的 todo 列表（新列表，不修改原列表）。
    """
    updated = list(todos)

    # 1. 标记 skipped
    skip_tasks = {s.task: s.reason for s in output.todos_to_skip}
    for i, todo in enumerate(updated):
        if todo.task in skip_tasks and todo.status == "pending":
            updated[i] = todo.model_copy(
                update={
                    "status": "skipped",
                    "conclusion": skip_tasks[todo.task],
                }
            )

    # 2. 新增 todo（受上限约束）
    new_todos = output.new_todos[:MAX_NEW_TODOS_PER_EVAL]
    remaining_capacity = MAX_TODOS - len(updated)
    for nt in new_todos[:max(0, remaining_capacity)]:
        updated.append(
            TodoItem(
                task=nt.task,
                context=nt.context,
                added_by="evaluate",
            )
        )

    return updated
