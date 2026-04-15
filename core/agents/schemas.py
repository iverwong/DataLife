"""结构化输出 Pydantic Schema。

供 plan 和 evaluate 节点通过 with_structured_output 使用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.agents.base import MAX_NEW_TODOS_PER_EVAL


class PlanTodo(BaseModel):
    """plan 节点输出的单个调研任务。"""

    task: str = Field(description="具体要做什么，如'搜索贵州茅台2025年年报'")
    context: str = Field(description="为什么要做这个任务（背景/动机）")


class PlanOutput(BaseModel):
    """plan 节点的结构化输出。"""

    todos: list[PlanTodo] = Field(
        description="拆解出的 1~8 个调研任务列表",
        min_length=1,
        max_length=8,
    )


class EvaluateNewTodo(BaseModel):
    """evaluate 节点新增的调研任务。"""

    task: str = Field(description="新任务描述")
    context: str = Field(description="为什么需要补充这个调研")


class EvaluateSkipTodo(BaseModel):
    """evaluate 节点要跳过的任务。"""

    task: str = Field(description="要跳过的任务描述（需与 todo 列表中的 task 匹配）")
    reason: str = Field(description="跳过原因")


class EvaluateOutput(BaseModel):
    """evaluate 节点的结构化输出。"""

    notes_update: str = Field(description="本轮新发现的要点摘要，将追加到已有笔记中")
    new_todos: list[EvaluateNewTodo] = Field(
        default_factory=list,
        description=f"需要补充的新调研任务（最多 {MAX_NEW_TODOS_PER_EVAL} 个）",
        max_length=MAX_NEW_TODOS_PER_EVAL,
    )
    todos_to_skip: list[EvaluateSkipTodo] = Field(
        default_factory=list,
        description="不再需要执行的 pending 任务",
    )
