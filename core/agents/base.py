"""公告查询 Agent 通用骨架。

State 定义和控制常量，可被未来其他 Agent 复用。
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage

# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

# ── 控制常量 ──────────────────────────────────────────

MAX_ITERATIONS: int = 20
"""evaluate 轮次上限，超出强制进入 synthesize。"""

MAX_TOKENS: int = 200_000
"""累积 token 消耗上限。"""

MAX_TODOS: int = 10
"""todo 总数上限，防止任务膨胀。"""

MAX_NEW_TODOS_PER_EVAL: int = 2
"""evaluate 每轮最多新增 todo 数。"""

# ── 数据模型 ──────────────────────────────────────────


class TodoItem(BaseModel):
    """Agent 任务列表中的单个任务。

    Attributes:
        task: 具体要做什么。
        context: 为什么要做（背景/动机，给执行者判断用）。
        status: 任务状态。
        conclusion: 执行结论或跳过原因。
        added_by: 任务来源节点。
    """

    task: str
    context: str = ""
    status: Literal["pending", "in_progress", "done", "skipped"] = "pending"
    conclusion: str = ""
    added_by: Literal["plan", "evaluate"] = "plan"


class AgentState(BaseModel):
    """公告查询 Agent 的共享状态。

    所有节点读写此状态实现协作。
    Pydantic BaseModel 提供输入校验。

    Reducer 策略：
    - messages: add_messages（追加 + 去重）
    - announcements_seen: operator.add（追加）
    - total_tokens: operator.add（累加）
    - todos / notes / iteration: 无 reducer，节点返回值直接覆盖
    """

    # 输入
    question: str

    # 任务管理（无 reducer，节点返回完整列表覆盖）
    todos: list[TodoItem] = Field(default_factory=list)

    # 流转数据
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    notes: str = ""
    announcements_seen: Annotated[list[str], operator.add] = Field(default_factory=list)

    # 控制
    iteration: int = 0
    total_tokens: Annotated[int, operator.add] = 0
