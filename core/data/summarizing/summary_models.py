"""Step 3 摘要输出数据模型。

所有摘要阶段（单 Chunk 摘要、子块摘要、章节合并摘要）使用统一输出结构。
依赖：pydantic.BaseModel
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class SummarizeContext:
    """摘要上下文依赖，注入 Agent 的 deps。

    Attributes:
        context_brief: 前一个 Chunk 的 context_brief，None 表示当前为首块
        chapter_path: 当前 Chunk 的章节路径
        contained_chapters: 当前 Chunk 包含的章节列表（多章节场景）
        chunk_index: 当前 Chunk 在章节内的索引
    """

    context_brief: str | None
    chapter_path: list[str]
    contained_chapters: list[str] | None
    chunk_index: int


class PeriodInfo(BaseModel):
    """时间维度信息。

    兼容精确日期和语义描述：
    - 时间节点（调研日、登记日等）：填 start_date，不填 end_date
    - 时间区间（年度、季度等）：填 start_date + end_date
    - description 始终填写，保留原文时间表述
    - LLM 能确定精确日期时填日期字段；不确定时只填 description
    """

    start_date: str | None = None
    end_date: str | None = None
    description: str = ""


class KeyDataItem(BaseModel):
    """结构化关键数据条目。

    - label：语义标签（如 "营业收入"），尽量使用规范化表述
    - value：float | None，确保机读性；无法量化的定性描述 value 为 None
    - unit：量词（如 "元"、"%"、"股"），不做严格枚举
    - period：时间维度，记录数据所属时间范围
    - remark：补充说明（如 "扣非后"、"经审计"）
    """

    label: str
    value: float | None = None
    unit: str = ""
    period: PeriodInfo | None = None
    remark: str = ""


class ChunkSummaryOutput(BaseModel):
    """统一摘要输出模型。

    单 Chunk 摘要、子块摘要、章节合并摘要均使用此结构。
    PydanticAI Agent 的 output_type 即为此模型。
    """

    chapter_title: str = Field(description="章节标题")
    chapter_path: list[str] = Field(
        description="章节路径，如 ['第三节 管理层讨论', '3.2 主营业务']"
    )
    key_points: list[str] = Field(description="核心要点，3-5 条关键信息提炼")
    detailed_summary: str = Field(description="详细摘要，该章节/块的内容概述")
    key_data: list[KeyDataItem] = Field(
        default_factory=list, description="结构化关键数据抽取"
    )
    context_brief: str = Field(
        description="精简上下文提示（3~5 句话），供下一个 LLM 使用"
    )


class ChapterSummary(BaseModel):
    """章节级摘要结果。

    代表一个章节的最终摘要（可能来自单 Chunk 直出或多 Chunk 合并）。
    用于最终文档拼接。
    """

    chapter_title: str
    chapter_path: list[str]
    summary: ChunkSummaryOutput
    chunk_count: int = Field(description="该章节包含的 Chunk 数量，1 表示单 Chunk 直出")


class DocumentSummary(BaseModel):
    """完整文档摘要输出。

    包含分章节摘要、全文核心要点汇总、关键数据汇总。
    """

    source: str = Field(description="文档来源标识，如股票代码+报告日期")
    chapter_summaries: list[ChapterSummary] = Field(
        description="按原文顺序排列的各章节摘要"
    )
    all_key_points: list[str] = Field(
        description="全文核心要点（各章节 key_points 汇聚）"
    )
    all_key_data: list[KeyDataItem] = Field(
        description="全文关键数据汇总（各章节 key_data 合并）"
    )
    total_chunks_processed: int
    total_chapters: int
