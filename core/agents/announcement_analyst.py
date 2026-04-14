"""公告查询 Agent 图组装。

图结构：START → plan → research → evaluate →[条件边]→ synthesize → END
                                      ↑                    │
                                      └── "有 pending" ────┘
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph import (
    END,
    START,
    StateGraph,
)
from langgraph.graph.state import (
    CompiledStateGraph,
)

from core.agents.base import (
    MAX_ITERATIONS,
    MAX_TOKENS,
    AgentState,
)
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
    raise NotImplementedError


async def research(
    state: AgentState,
    model_with_tools: BaseChatModel,
    tools: list[Any],
) -> dict[str, Any]:
    """执行节点：取第一个 pending todo，通过手动 ReAct 循环执行工具调用。

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
    raise NotImplementedError


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
    raise NotImplementedError


async def synthesize(state: AgentState, model: BaseChatModel) -> dict[str, Any]:
    """输出节点：基于 todos + notes 生成最终分析报告。

    Args:
        state: 当前图状态（读取 todos, notes）。
        model: LLM 实例。

    Returns:
        状态更新 dict，包含 notes（最终分析文本）和 total_tokens。
    """
    raise NotImplementedError


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
    model_with_tools = model.bind_tools(tools)

    async def _plan(state: AgentState) -> dict[str, Any]:
        return await plan(state, model)

    async def _research(state: AgentState) -> dict[str, Any]:
        return await research(state, model_with_tools, tools)

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
