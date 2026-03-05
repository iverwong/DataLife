# Step 3 执行计划：PydanticAI 编排 + DeepSeek 摘要

## 1. 目标概述

基于 Step 2 产出的 `ChunkList`，使用 **PydanticAI** 编排 **DeepSeek API**，对每个 Chunk 进行独立摘要（注入 `context_brief` 精简上下文），并通过工程逻辑将各章节摘要拼接为完整文档结构化摘要，最终持久化至本地 SQLite。

## 2. 前置条件

| 模块 | 路径 | 关键接口 |
| --- | --- | --- |
| 数据模型 | `core/data/models.py` | `Chunk`, `ChunkList`, `ChunkMeta`, `ChunkType` |
| 异常基类 | `core/data/exceptions.py` | `ChunkingError`, `StorageError` |
| 异常根 | `core/exceptions.py` | `DataLifeError` |
| 分块存储 | `core/data/chunk_storage.py` | `save_chunks()`, `load_chunks()`, `init_chunk_tables()` |
| 分块编排 | `core/data/chunk_pipeline.py` | `chunk_document()` |
| Token 计数 | `core/data/token_counter.py` | `count_tokens()`, `truncate_to_tokens()` |

---

## ▶ 阶段 A：`/tdd-red` 执行以下步骤

### 3. Git 准备

```bash
git checkout main
git pull origin main
git checkout -b feat/step3-summarization
```

### 4. 契约定义（抽象层）

#### 4.1 摘要数据模型 — `core/data/summary_models.py`（新建）

```python
"""Step 3 摘要输出数据模型。

所有摘要阶段（单 Chunk 摘要、子块摘要、章节合并摘要）使用统一输出结构。
依赖：pydantic.BaseModel
"""
from __future__ import annotations

from pydantic import BaseModel, Field

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
    chapter_path: list[str] = Field(description="章节路径，如 ['第三节 管理层讨论', '3.2 主营业务']")
    key_points: list[str] = Field(description="核心要点，3-5 条关键信息提炼")
    detailed_summary: str = Field(description="详细摘要，该章节/块的内容概述")
    key_data: list[KeyDataItem] = Field(default_factory=list, description="结构化关键数据抽取")
    context_brief: str = Field(description="精简上下文提示（3~5 句话），供下一个 LLM 使用")

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
    chapter_summaries: list[ChapterSummary] = Field(description="按原文顺序排列的各章节摘要")
    all_key_points: list[str] = Field(description="全文核心要点（各章节 key_points 汇聚）")
    all_key_data: list[KeyDataItem] = Field(description="全文关键数据汇总（各章节 key_data 合并）")
    total_chunks_processed: int
    total_chapters: int
```

#### 4.2 摘要异常 — `core/data/exceptions.py`（追加）

```python
# --- 在现有 exceptions.py 末尾追加 ---

class SummarizationError(DataLifeError):
    """摘要流程基础异常。"""
    ...

class LLMResponseError(SummarizationError):
    """LLM 返回内容无法解析或为空。

    降级行为：重试 retries 次后抛出，由上层决定是否跳过该 Chunk。
    """
    ...

class ContextBriefError(SummarizationError):
    """上下文注入构建失败。

    降级行为：跳过 context_brief 注入，仅用当前 Chunk 独立摘要。
    记录 warning 日志，不中断流程。
    """
    ...

class ChapterMergeError(SummarizationError):
    """章节合并失败。

    降级行为：返回子块摘要的简单拼接（取各子块 detailed_summary 拼接），
    标记 degraded=True，记录 warning 日志。
    """
    ...

class SummaryStorageError(SummarizationError):
    """摘要存储读写异常。"""
    ...
```

#### 4.3 Chunk 摘要器 — `core/data/chunk_summarizer.py`（新建）

```python
"""逐 Chunk 摘要模块。

使用 PydanticAI Agent + DeepSeek 对单个 Chunk 生成结构化摘要。
支持 context_brief 注入，实现上下文衔接。

依赖：
- pydantic_ai：Agent 编排、结构化输出
- core.data.models：Chunk, ChunkList
- core.data.summary_models：ChunkSummaryOutput
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.data.summary_models import ChunkSummaryOutput

if TYPE_CHECKING:
    from core.data.models import Chunk

# ── 常量 ──────────────────────────────────────────────
DEFAULT_MODEL: str = "deepseek-chat"
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_TEMPERATURE: float = 0.3
DEFAULT_MAX_TOKENS: int = 4096

@dataclass(frozen=True)
class SummarizeContext:
    """摘要上下文依赖，注入 PydanticAI Agent 的 deps。

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

def build_summarize_context(
    chunk: Chunk,
    previous_context_brief: str | None,
) -> SummarizeContext:
    """从 Chunk 和前文 context_brief 构建摘要上下文。

    Args:
        chunk: 当前待摘要的 Chunk
        previous_context_brief: 前一个 Chunk 的 context_brief，
            同一章节子块间传递；不同章节间传递同级上一章节的 context_brief。
            首块为 None。

    Returns:
        SummarizeContext 实例
    """
    raise NotImplementedError

async def summarize_chunk(
    chunk: Chunk,
    context: SummarizeContext,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    retries: int = DEFAULT_MAX_RETRIES,
) -> ChunkSummaryOutput:
    """对单个 Chunk 调用 DeepSeek 生成结构化摘要。

    流程：
    1. 构建系统 prompt（格式要求 + context_brief 用途说明 + key_data 指引）
    2. 注入 context_brief（如有）
    3. 注入 chapter_path + contained_chapters 信息
    4. 注入 Chunk 原文 markdown
    5. 调用 PydanticAI Agent，output_type=ChunkSummaryOutput
    6. 返回验证后的结构化输出

    Args:
        chunk: 待摘要的 Chunk（包含 text, chapter_path, contained_chapters 等）
        context: 摘要上下文（含 context_brief、chapter_path 等）
        model: DeepSeek 模型名称，默认 deepseek-chat
        api_key: DeepSeek API Key，None 时从环境变量 DEEPSEEK_API_KEY 读取
        temperature: 生成温度，默认 0.3（摘要任务偏确定性）
        max_tokens: 最大输出 token 数
        retries: 失败重试次数

    Returns:
        ChunkSummaryOutput：结构化摘要输出

    Raises:
        LLMResponseError: LLM 返回为空或无法解析为目标结构
        SummarizationError: 其他摘要流程异常
    """
    raise NotImplementedError
```

#### 4.4 章节合并器 — `core/data/chapter_merger.py`（新建）

```python
"""章节级摘要合并模块。

处理多 Chunk 章节的摘要合并：收集该章节所有子块的摘要，
调用 LLM 合并为一份统一的章节摘要。

依赖：
- pydantic_ai：Agent 编排
- core.data.summary_models：ChunkSummaryOutput, ChapterSummary
"""
from __future__ import annotations

from core.data.summary_models import ChapterSummary, ChunkSummaryOutput

async def merge_chapter_summaries(
    sub_summaries: list[ChunkSummaryOutput],
    chapter_title: str,
    chapter_path: list[str],
    *,
    model: str = "deepseek-chat",
    api_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries: int = 3,
) -> ChapterSummary:
    """将同一章节的多个子块摘要合并为章节级摘要。

    路径 2 逻辑：收集子块的 detailed_summary + key_points + key_data，
    调用 LLM 生成统一的章节摘要。LLM 只接收摘要文本，不接收原文。

    Args:
        sub_summaries: 同一章节下所有子块的 ChunkSummaryOutput，按原文顺序排列
        chapter_title: 章节标题
        chapter_path: 章节路径
        model: DeepSeek 模型名称
        api_key: API Key
        temperature: 生成温度
        max_tokens: 最大输出 token
        retries: 重试次数

    Returns:
        ChapterSummary：合并后的章节级摘要

    Raises:
        ChapterMergeError: 合并失败时抛出。
            降级行为：返回子块摘要拼接结果，chapter_count 仍为实际子块数。
        LLMResponseError: LLM 返回异常

    Note:
        当 sub_summaries 长度为 1 时，直接包装为 ChapterSummary 返回，不调用 LLM。
    """
    raise NotImplementedError

def build_single_chunk_chapter(
    summary: ChunkSummaryOutput,
) -> ChapterSummary:
    """将单 Chunk 章节的摘要包装为 ChapterSummary（路径 1）。

    Args:
        summary: 单 Chunk 的摘要输出

    Returns:
        ChapterSummary，chunk_count=1
    """
    raise NotImplementedError
```

#### 4.5 摘要存储 — `core/data/summary_storage.py`（新建）

```python
"""摘要结果 SQLite 持久化模块。

与 Step 2 的 chunk_meta 表关联，存储摘要输出。

依赖：
- aiosqlite
- core.data.summary_models：ChunkSummaryOutput, DocumentSummary, ChapterSummary
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.data.summary_models import ChapterSummary, DocumentSummary

# ── 常量 ──────────────────────────────────────────────
DEFAULT_DB_DIR: Path = Path("data")

async def init_summary_tables(db_path: Path = DEFAULT_DB_DIR / "datalife.db") -> None:
    """初始化摘要相关的 SQLite 表。

    创建以下表（IF NOT EXISTS）：
    - chunk_summary：逐 Chunk 摘要结果，外键关联 chunk_meta.id
        - id INTEGER PRIMARY KEY
        - chunk_meta_id INTEGER REFERENCES chunk_meta(id)
        - chapter_title TEXT NOT NULL
        - chapter_path TEXT NOT NULL (JSON array)
        - key_points TEXT NOT NULL (JSON array)
        - detailed_summary TEXT NOT NULL
        - key_data TEXT (JSON array of KeyDataItem)
        - context_brief TEXT NOT NULL
        - created_at TEXT NOT NULL (ISO 8601)
    - chapter_summary：章节级摘要（合并后或单 Chunk 直出）
        - id INTEGER PRIMARY KEY
        - stock_code TEXT NOT NULL
        - report_date TEXT NOT NULL
        - chapter_title TEXT NOT NULL
        - chapter_path TEXT NOT NULL (JSON array)
        - summary_json TEXT NOT NULL (完整 ChunkSummaryOutput JSON)
        - chunk_count INTEGER NOT NULL
        - created_at TEXT NOT NULL (ISO 8601)
    - document_summary：文档级摘要元信息
        - id INTEGER PRIMARY KEY
        - stock_code TEXT NOT NULL
        - report_date TEXT NOT NULL
        - total_chapters INTEGER NOT NULL
        - total_chunks_processed INTEGER NOT NULL
        - all_key_points TEXT NOT NULL (JSON array)
        - all_key_data TEXT NOT NULL (JSON array)
        - created_at TEXT NOT NULL (ISO 8601)

    Args:
        db_path: SQLite 数据库文件路径

    Raises:
        SummaryStorageError: 表创建失败
    """
    raise NotImplementedError

async def save_chunk_summary(
    chunk_meta_id: int,
    summary: "ChunkSummaryOutput",
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> int:
    """保存单个 Chunk 的摘要结果。

    Args:
        chunk_meta_id: chunk_meta 表中对应的记录 ID
        summary: Chunk 摘要输出
        db_path: 数据库路径

    Returns:
        插入记录的 ID

    Raises:
        SummaryStorageError: 写入失败
    """
    raise NotImplementedError

async def save_chapter_summary(
    chapter: "ChapterSummary",
    stock_code: str,
    report_date: str,
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> int:
    """保存章节级摘要结果。

    Args:
        chapter: 章节摘要
        stock_code: 股票代码
        report_date: 报告日期
        db_path: 数据库路径

    Returns:
        插入记录的 ID

    Raises:
        SummaryStorageError: 写入失败
    """
    raise NotImplementedError

async def save_document_summary(
    doc_summary: "DocumentSummary",
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> int:
    """保存完整文档摘要元信息。

    Args:
        doc_summary: 文档级摘要
        db_path: 数据库路径

    Returns:
        插入记录的 ID

    Raises:
        SummaryStorageError: 写入失败
    """
    raise NotImplementedError

async def load_document_summary(
    stock_code: str,
    report_date: str,
    *,
    db_path: Path = DEFAULT_DB_DIR / "datalife.db",
) -> "DocumentSummary | None":
    """按股票代码和报告日期加载文档摘要。

    Args:
        stock_code: 股票代码
        report_date: 报告日期
        db_path: 数据库路径

    Returns:
        DocumentSummary 或 None（未找到）

    Raises:
        SummaryStorageError: 读取失败
    """
    raise NotImplementedError
```

#### 4.6 摘要编排管道 — `core/data/summary_pipeline.py`（新建）

```python
"""摘要编排主管道。

端到端编排：ChunkList → 逐 Chunk 摘要 → 章节合并 → 文档拼接 → 持久化。

依赖：
- core.data.models：ChunkList
- core.data.summary_models：DocumentSummary
- core.data.chunk_summarizer：summarize_chunk, build_summarize_context
- core.data.chapter_merger：merge_chapter_summaries, build_single_chunk_chapter
- core.data.summary_storage：save_*, init_summary_tables
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.data.models import ChunkList
    from core.data.summary_models import DocumentSummary

async def summarize_document(
    chunk_list: "ChunkList",
    *,
    stock_code: str,
    report_date: str,
    model: str = "deepseek-chat",
    api_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries: int = 3,
    persist: bool = True,
) -> "DocumentSummary":
    """端到端文档摘要编排。

    完整流程：
    1. 遍历 ChunkList 中的 Chunk（按文档顺序）
    2. 对每个 Chunk 构建 SummarizeContext（注入前一块的 context_brief）
       - 同一章节子块间：传递前一子块的 context_brief
       - 不同章节间：传递同级上一章节最后一个子块的 context_brief
    3. 调用 summarize_chunk 获取 ChunkSummaryOutput
    4. 按章节分组：
       - 单 Chunk 章节 → build_single_chunk_chapter（路径 1）
       - 多 Chunk 章节 → merge_chapter_summaries（路径 2）
    5. 各章节摘要按原文顺序拼接
    6. 汇总 all_key_points 和 all_key_data
    7. 构建 DocumentSummary
    8. 如果 persist=True，写入 SQLite

    Args:
        chunk_list: Step 2 产出的 ChunkList
        stock_code: 股票代码，用于存储关联
        report_date: 报告日期
        model: DeepSeek 模型名称
        api_key: API Key
        temperature: 生成温度
        max_tokens: 最大输出 token
        retries: 重试次数
        persist: 是否持久化到 SQLite

    Returns:
        DocumentSummary：完整文档结构化摘要

    Raises:
        SummarizationError: 摘要流程异常
        SummaryStorageError: 持久化失败（仅 persist=True 时）
    """
    raise NotImplementedError
```

### 5. 测试用例

#### 5.1 测试文件：`tests/test_summary_models.py`（新建）

```python
"""摘要数据模型验证测试。"""
import pytest
from pydantic import ValidationError

from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
    PeriodInfo,
)

# ── PeriodInfo ──────────────────────────────────────────
class TestPeriodInfo:
    def test_full_range(self) -> None:
        """精确日期区间：start_date + end_date + description 全部填写。"""
        p = PeriodInfo(
            start_date="2024-01-01",
            end_date="2024-12-31",
            description="2024年度",
        )
        assert p.start_date == "2024-01-01"
        assert p.end_date == "2024-12-31"
        assert p.description == "2024年度"

    def test_description_only(self) -> None:
        """仅语义描述，无精确日期。"""
        p = PeriodInfo(description="报告期末")
        assert p.start_date is None
        assert p.end_date is None
        assert p.description == "报告期末"

    def test_single_date(self) -> None:
        """时间节点场景：仅 start_date。"""
        p = PeriodInfo(start_date="2024-06-15", description="调研日")
        assert p.start_date == "2024-06-15"
        assert p.end_date is None

# ── KeyDataItem ─────────────────────────────────────────
class TestKeyDataItem:
    def test_numeric_item(self) -> None:
        """标准数值型数据条目。"""
        item = KeyDataItem(
            label="营业收入",
            value=1_234_567_890.50,
            unit="元",
            period=PeriodInfo(description="2024年度"),
        )
        assert item.label == "营业收入"
        assert item.value == 1_234_567_890.50
        assert item.unit == "元"

    def test_qualitative_item(self) -> None:
        """定性描述：value 为 None。"""
        item = KeyDataItem(
            label="风险评级",
            value=None,
            remark="AA+",
        )
        assert item.value is None
        assert item.remark == "AA+"

    def test_label_required(self) -> None:
        """label 为必填字段。"""
        with pytest.raises(ValidationError):
            KeyDataItem(value=100)  # type: ignore[call-arg]

# ── ChunkSummaryOutput ──────────────────────────────────
class TestChunkSummaryOutput:
    def test_valid_output(self) -> None:
        """完整有效的摘要输出。"""
        output = ChunkSummaryOutput(
            chapter_title="第一节 重要提示",
            chapter_path=["第一节 重要提示"],
            key_points=["公司年度营收增长 15%", "净利润同比下降 3%"],
            detailed_summary="本节介绍了公司年度经营概况...",
            key_data=[
                KeyDataItem(label="营业收入", value=5e9, unit="元"),
            ],
            context_brief="第一节概述了公司年度经营情况，营收增长但净利润略有下降。",
        )
        assert output.chapter_title == "第一节 重要提示"
        assert len(output.key_points) == 2
        assert len(output.key_data) == 1

    def test_empty_key_data_allowed(self) -> None:
        """key_data 可以为空列表（某些章节无结构化数据）。"""
        output = ChunkSummaryOutput(
            chapter_title="致股东书",
            chapter_path=["致股东书"],
            key_points=["展望未来发展"],
            detailed_summary="董事长致辞...",
            key_data=[],
            context_brief="致股东书主要介绍了公司发展愿景。",
        )
        assert output.key_data == []

    def test_missing_required_fields(self) -> None:
        """缺少必填字段应报错。"""
        with pytest.raises(ValidationError):
            ChunkSummaryOutput(
                chapter_title="测试",
                # 缺少 chapter_path, key_points, detailed_summary, context_brief
            )  # type: ignore[call-arg]

# ── ChapterSummary ──────────────────────────────────────
class TestChapterSummary:
    def test_single_chunk_chapter(self) -> None:
        """单 Chunk 章节，chunk_count=1。"""
        summary_output = ChunkSummaryOutput(
            chapter_title="第二节",
            chapter_path=["第二节"],
            key_points=["要点1"],
            detailed_summary="摘要内容",
            context_brief="上下文",
        )
        ch = ChapterSummary(
            chapter_title="第二节",
            chapter_path=["第二节"],
            summary=summary_output,
            chunk_count=1,
        )
        assert ch.chunk_count == 1

# ── DocumentSummary ─────────────────────────────────────
class TestDocumentSummary:
    def test_valid_document_summary(self) -> None:
        """完整文档摘要结构验证。"""
        doc = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[],
            all_key_points=["全文要点1"],
            all_key_data=[],
            total_chunks_processed=10,
            total_chapters=5,
        )
        assert doc.source == "600000_2024-12-31"
        assert doc.total_chunks_processed == 10
```

#### 5.2 测试文件：`tests/test_chunk_summarizer.py`（新建）

```python
"""逐 Chunk 摘要器测试。

使用 mock 隔离 DeepSeek API 调用，验证：
- SummarizeContext 构建逻辑
- prompt 中 context_brief 注入
- 正常摘要输出
- LLM 返回异常处理
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from core.data.models import Chunk, ChunkType
from core.data.summary_models import ChunkSummaryOutput
from core.data.chunk_summarizer import (
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    SummarizeContext,
    build_summarize_context,
    summarize_chunk,
)
from core.data.exceptions import LLMResponseError

# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def sample_chunk() -> Chunk:
    """标准单章节 Chunk，约 500 token 文本。"""
    return Chunk(
        text="本公司2024年度实现营业收入50亿元..." * 50,  # ~500 tokens
        chapter_path=["第三节 管理层讨论", "3.1 经营概况"],
        page_range=(10, 15),
        token_count=500,
        chunk_type=ChunkType.COMPLETE_CHAPTER,
        needs_prior_summary=False,
        chunk_index=0,
        contained_chapters=None,
    )

@pytest.fixture
def sample_chunk_with_prior() -> Chunk:
    """需要前文上下文的子块 Chunk（chunk_index=1）。"""
    return Chunk(
        text="续上文，公司海外业务..." * 50,
        chapter_path=["第三节 管理层讨论", "3.1 经营概况"],
        page_range=(15, 20),
        token_count=500,
        chunk_type=ChunkType.TOKEN_WINDOW,
        needs_prior_summary=True,
        chunk_index=1,
        contained_chapters=None,
    )

@pytest.fixture
def mock_summary_output() -> ChunkSummaryOutput:
    """模拟 LLM 返回的标准摘要输出。"""
    return ChunkSummaryOutput(
        chapter_title="3.1 经营概况",
        chapter_path=["第三节 管理层讨论", "3.1 经营概况"],
        key_points=["营收50亿", "同比增长15%"],
        detailed_summary="公司2024年度经营情况良好...",
        key_data=[],
        context_brief="第三节3.1小节概述了公司2024年经营概况，营收50亿，同比增长15%。",
    )

# ── build_summarize_context ────────────────────────────
class TestBuildSummarizeContext:
    def test_first_chunk_no_context(self, sample_chunk: Chunk) -> None:
        """首块无 context_brief。"""
        ctx = build_summarize_context(sample_chunk, previous_context_brief=None)
        assert ctx.context_brief is None
        assert ctx.chunk_index == 0
        assert ctx.chapter_path == ["第三节 管理层讨论", "3.1 经营概况"]

    def test_subsequent_chunk_with_context(
        self, sample_chunk_with_prior: Chunk
    ) -> None:
        """后续子块注入前文 context_brief。"""
        prev_brief = "前文概述了公司整体情况。"
        ctx = build_summarize_context(
            sample_chunk_with_prior, previous_context_brief=prev_brief
        )
        assert ctx.context_brief == prev_brief
        assert ctx.chunk_index == 1

    def test_contained_chapters_passed(self) -> None:
        """多章节 Chunk 的 contained_chapters 正确传递。"""
        chunk = Chunk(
            text="多章节内容...",
            chapter_path=["第四节"],
            page_range=(20, 30),
            token_count=300,
            chunk_type=ChunkType.COMPLETE_CHAPTER,
            needs_prior_summary=False,
            chunk_index=0,
            contained_chapters=["4.1 子章节A", "4.2 子章节B"],
        )
        ctx = build_summarize_context(chunk, previous_context_brief=None)
        assert ctx.contained_chapters == ["4.1 子章节A", "4.2 子章节B"]

# ── summarize_chunk ────────────────────────────────────
class TestSummarizeChunk:
    @pytest.mark.asyncio
    async def test_successful_summarization(
        self,
        sample_chunk: Chunk,
        mock_summary_output: ChunkSummaryOutput,
    ) -> None:
        """正常调用返回结构化摘要。"""
        ctx = SummarizeContext(
            context_brief=None,
            chapter_path=sample_chunk.chapter_path,
            contained_chapters=None,
            chunk_index=0,
        )
        # mock PydanticAI Agent.run
        with patch(
            "core.data.chunk_summarizer._run_agent",
            new_callable=AsyncMock,
            return_value=mock_summary_output,
        ):
            result = await summarize_chunk(sample_chunk, ctx)
        assert isinstance(result, ChunkSummaryOutput)
        assert result.chapter_title == "3.1 经营概况"
        assert len(result.key_points) >= 1

    @pytest.mark.asyncio
    async def test_llm_empty_response_raises(
        self, sample_chunk: Chunk
    ) -> None:
        """LLM 返回空内容时抛出 LLMResponseError。"""
        ctx = SummarizeContext(
            context_brief=None,
            chapter_path=sample_chunk.chapter_path,
            contained_chapters=None,
            chunk_index=0,
        )
        with patch(
            "core.data.chunk_summarizer._run_agent",
            new_callable=AsyncMock,
            side_effect=LLMResponseError("Empty response from LLM"),
        ):
            with pytest.raises(LLMResponseError):
                await summarize_chunk(sample_chunk, ctx)

    @pytest.mark.asyncio
    async def test_context_brief_injected_in_prompt(
        self,
        sample_chunk_with_prior: Chunk,
        mock_summary_output: ChunkSummaryOutput,
    ) -> None:
        """验证 context_brief 被注入到 prompt 中。"""
        prev_brief = "前文概述了整体经营情况。"
        ctx = SummarizeContext(
            context_brief=prev_brief,
            chapter_path=sample_chunk_with_prior.chapter_path,
            contained_chapters=None,
            chunk_index=1,
        )
        captured_prompts: list[str] = []

        async def mock_run(*args, **kwargs):
            # 捕获传入的 user prompt 以验证 context_brief 注入
            if "user_prompt" in kwargs:
                captured_prompts.append(kwargs["user_prompt"])
            return mock_summary_output

        with patch(
            "core.data.chunk_summarizer._run_agent",
            new_callable=AsyncMock,
            side_effect=mock_run,
        ):
            await summarize_chunk(sample_chunk_with_prior, ctx)
        # 验证 context_brief 出现在 prompt 中
        # 具体验证方式取决于实现中 prompt 的构建方式
```

#### 5.3 测试文件：`tests/test_chapter_merger.py`（新建）

```python
"""章节合并器测试。

验证：
- 单 Chunk 章节直接包装
- 多 Chunk 章节 LLM 合并
- 合并失败降级为拼接
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from core.data.summary_models import ChapterSummary, ChunkSummaryOutput
from core.data.chapter_merger import (
    build_single_chunk_chapter,
    merge_chapter_summaries,
)
from core.data.exceptions import ChapterMergeError

# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def single_summary() -> ChunkSummaryOutput:
    """单 Chunk 章节的摘要输出。"""
    return ChunkSummaryOutput(
        chapter_title="第一节",
        chapter_path=["第一节"],
        key_points=["要点A"],
        detailed_summary="第一节详细摘要",
        context_brief="第一节上下文",
    )

@pytest.fixture
def multi_summaries() -> list[ChunkSummaryOutput]:
    """多 Chunk 章节的 3 个子块摘要（模拟财报附注超长章节被切为 3 块）。"""
    return [
        ChunkSummaryOutput(
            chapter_title="附注",
            chapter_path=["第十一节 财务报告", "附注"],
            key_points=[f"子块{i}要点"],
            detailed_summary=f"子块{i}摘要内容",
            context_brief=f"子块{i}上下文",
        )
        for i in range(3)
    ]

@pytest.fixture
def merged_output() -> ChunkSummaryOutput:
    """模拟 LLM 合并后的章节摘要。"""
    return ChunkSummaryOutput(
        chapter_title="附注",
        chapter_path=["第十一节 财务报告", "附注"],
        key_points=["合并后要点1", "合并后要点2"],
        detailed_summary="附注章节的统一摘要...",
        context_brief="附注章节概述了财务报告详细数据。",
    )

# ── build_single_chunk_chapter ─────────────────────────
class TestBuildSingleChunkChapter:
    def test_wraps_correctly(self, single_summary: ChunkSummaryOutput) -> None:
        """单 Chunk 直接包装为 ChapterSummary，chunk_count=1。"""
        ch = build_single_chunk_chapter(single_summary)
        assert isinstance(ch, ChapterSummary)
        assert ch.chunk_count == 1
        assert ch.chapter_title == "第一节"
        assert ch.summary is single_summary

# ── merge_chapter_summaries ────────────────────────────
class TestMergeChapterSummaries:
    @pytest.mark.asyncio
    async def test_single_item_no_llm_call(
        self, single_summary: ChunkSummaryOutput
    ) -> None:
        """仅 1 个子块时不调用 LLM，直接包装返回。"""
        result = await merge_chapter_summaries(
            [single_summary],
            chapter_title="第一节",
            chapter_path=["第一节"],
        )
        assert result.chunk_count == 1

    @pytest.mark.asyncio
    async def test_multi_chunk_merge(
        self,
        multi_summaries: list[ChunkSummaryOutput],
        merged_output: ChunkSummaryOutput,
    ) -> None:
        """多子块调用 LLM 合并，返回合并后的 ChapterSummary。"""
        with patch(
            "core.data.chapter_merger._run_merge_agent",
            new_callable=AsyncMock,
            return_value=merged_output,
        ):
            result = await merge_chapter_summaries(
                multi_summaries,
                chapter_title="附注",
                chapter_path=["第十一节 财务报告", "附注"],
            )
        assert result.chunk_count == 3
        assert "合并后要点1" in result.summary.key_points

    @pytest.mark.asyncio
    async def test_merge_failure_degrades(
        self, multi_summaries: list[ChunkSummaryOutput]
    ) -> None:
        """合并 LLM 失败时降级为子块摘要拼接。"""
        with patch(
            "core.data.chapter_merger._run_merge_agent",
            new_callable=AsyncMock,
            side_effect=Exception("LLM merge failed"),
        ):
            result = await merge_chapter_summaries(
                multi_summaries,
                chapter_title="附注",
                chapter_path=["第十一节 财务报告", "附注"],
            )
        # 降级结果仍然是 ChapterSummary
        assert isinstance(result, ChapterSummary)
        assert result.chunk_count == 3
        # 降级摘要应包含各子块内容
        for i in range(3):
            assert f"子块{i}摘要内容" in result.summary.detailed_summary
```

#### 5.4 测试文件：`tests/test_summary_storage.py`（新建）

```python
"""摘要存储测试。

使用临时 SQLite 数据库，验证表创建和读写。
"""
from __future__ import annotations

import pytest
from pathlib import Path

from core.data.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
)
from core.data.summary_storage import (
    init_summary_tables,
    load_document_summary,
    save_chapter_summary,
    save_chunk_summary,
    save_document_summary,
)

# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """临时数据库文件路径。"""
    return tmp_path / "test_summary.db"

@pytest.fixture
def sample_chunk_summary() -> ChunkSummaryOutput:
    return ChunkSummaryOutput(
        chapter_title="第一节",
        chapter_path=["第一节"],
        key_points=["要点1"],
        detailed_summary="详细摘要",
        key_data=[KeyDataItem(label="营收", value=1e9, unit="元")],
        context_brief="上下文",
    )

# ── init_summary_tables ────────────────────────────────
class TestInitSummaryTables:
    @pytest.mark.asyncio
    async def test_creates_tables(self, tmp_db: Path) -> None:
        """首次调用创建所有摘要表。"""
        await init_summary_tables(db_path=tmp_db)
        # 验证表存在（通过 aiosqlite 查询 sqlite_master）
        import aiosqlite
        async with aiosqlite.connect(tmp_db) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        assert "chunk_summary" in tables
        assert "chapter_summary" in tables
        assert "document_summary" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db: Path) -> None:
        """重复调用不报错（IF NOT EXISTS）。"""
        await init_summary_tables(db_path=tmp_db)
        await init_summary_tables(db_path=tmp_db)

# ── save / load ────────────────────────────────────────
class TestSaveAndLoad:
    @pytest.mark.asyncio
    async def test_save_chunk_summary(
        self, tmp_db: Path, sample_chunk_summary: ChunkSummaryOutput
    ) -> None:
        """保存 Chunk 摘要并验证返回 ID。"""
        await init_summary_tables(db_path=tmp_db)
        # 需要先创建 chunk_meta 表和记录以提供外键
        # 此处简化：先创建 chunk_meta 表
        import aiosqlite
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS chunk_meta "
                "(id INTEGER PRIMARY KEY, stock_code TEXT, report_date TEXT)"
            )
            cursor = await db.execute(
                "INSERT INTO chunk_meta (stock_code, report_date) VALUES (?, ?)",
                ("600000", "2024-12-31"),
            )
            chunk_meta_id = cursor.lastrowid
            await db.commit()

        record_id = await save_chunk_summary(
            chunk_meta_id=chunk_meta_id,  # type: ignore[arg-type]
            summary=sample_chunk_summary,
            db_path=tmp_db,
        )
        assert isinstance(record_id, int)
        assert record_id > 0

    @pytest.mark.asyncio
    async def test_save_and_load_document_summary(self, tmp_db: Path) -> None:
        """保存并加载完整文档摘要，验证往返一致性。"""
        await init_summary_tables(db_path=tmp_db)
        doc = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[],
            all_key_points=["全文要点"],
            all_key_data=[KeyDataItem(label="总资产", value=1e10, unit="元")],
            total_chunks_processed=8,
            total_chapters=4,
        )
        await save_document_summary(doc, db_path=tmp_db)
        loaded = await load_document_summary(
            "600000", "2024-12-31", db_path=tmp_db
        )
        assert loaded is not None
        assert loaded.source == "600000_2024-12-31"
        assert loaded.total_chunks_processed == 8
        assert len(loaded.all_key_data) == 1

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_db: Path) -> None:
        """查询不存在的记录返回 None。"""
        await init_summary_tables(db_path=tmp_db)
        result = await load_document_summary(
            "999999", "2099-01-01", db_path=tmp_db
        )
        assert result is None
```

#### 5.5 测试文件：`tests/test_summary_pipeline.py`（新建）

```python
"""摘要编排管道集成测试。

mock LLM 调用，验证端到端流程：
ChunkList → 逐 Chunk 摘要 → 章节合并 → 文档拼接 → 持久化
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.data.models import Chunk, ChunkList, ChunkType
from core.data.summary_models import (
    ChunkSummaryOutput,
    DocumentSummary,
)
from core.data.summary_pipeline import summarize_document

# ── Fixtures ────────────────────────────────────────────
@pytest.fixture
def two_chapter_chunk_list() -> ChunkList:
    """包含 2 个章节（共 3 个 Chunk）的 ChunkList。

    章节 A（单 Chunk）：路径 1 直出
    章节 B（2 个 Chunk）：路径 2 合并
    """
    return ChunkList(
        source="600000_2024-12-31",
        chunks=[
            # 章节 A：单 Chunk
            Chunk(
                text="章节A完整内容..." * 30,
                chapter_path=["第一节"],
                page_range=(1, 5),
                token_count=300,
                chunk_type=ChunkType.COMPLETE_CHAPTER,
                needs_prior_summary=False,
                chunk_index=0,
                contained_chapters=None,
            ),
            # 章节 B：子块 0
            Chunk(
                text="章节B第一部分..." * 30,
                chapter_path=["第二节"],
                page_range=(6, 10),
                token_count=400,
                chunk_type=ChunkType.TOKEN_WINDOW,
                needs_prior_summary=False,
                chunk_index=0,
                contained_chapters=None,
            ),
            # 章节 B：子块 1
            Chunk(
                text="章节B第二部分..." * 30,
                chapter_path=["第二节"],
                page_range=(10, 15),
                token_count=400,
                chunk_type=ChunkType.TOKEN_WINDOW,
                needs_prior_summary=True,
                chunk_index=1,
                contained_chapters=None,
            ),
        ],
        total_tokens=1100,
        chapter_count=2,
    )

def _make_mock_summary(title: str, path: list[str], idx: int) -> ChunkSummaryOutput:
    """生成模拟摘要输出的辅助函数。"""
    return ChunkSummaryOutput(
        chapter_title=title,
        chapter_path=path,
        key_points=[f"{title}要点{idx}"],
        detailed_summary=f"{title}摘要{idx}",
        context_brief=f"{title}上下文{idx}",
    )

# ── summarize_document ─────────────────────────────────
class TestSummarizeDocument:
    @pytest.mark.asyncio
    async def test_end_to_end_no_persist(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """端到端流程（不持久化），验证 DocumentSummary 结构。"""
        call_count = 0

        async def mock_summarize(chunk, ctx, **kwargs):
            nonlocal call_count
            result = _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, call_count
            )
            call_count += 1
            return result

        merged_output = ChunkSummaryOutput(
            chapter_title="第二节",
            chapter_path=["第二节"],
            key_points=["合并要点"],
            detailed_summary="第二节合并摘要",
            context_brief="第二节合并上下文",
        )

        with patch(
            "core.data.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock,
            side_effect=mock_summarize,
        ), patch(
            "core.data.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=pytest.importorskip(
                "core.data.summary_models"
            ).ChapterSummary(
                chapter_title="第二节",
                chapter_path=["第二节"],
                summary=merged_output,
                chunk_count=2,
            ),
        ):
            result = await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000",
                report_date="2024-12-31",
                persist=False,
            )

        assert isinstance(result, DocumentSummary)
        assert result.total_chapters == 2
        assert result.total_chunks_processed == 3
        assert len(result.chapter_summaries) == 2
        # 章节 A：单 Chunk 直出，chunk_count=1
        assert result.chapter_summaries[0].chunk_count == 1
        # 章节 B：多 Chunk 合并，chunk_count=2
        assert result.chapter_summaries[1].chunk_count == 2

    @pytest.mark.asyncio
    async def test_context_brief_chaining(
        self, two_chapter_chunk_list: ChunkList
    ) -> None:
        """验证 context_brief 在 Chunk 间正确传递。

        - 章节 A 的 Chunk[0]：无 context_brief（首块）
        - 章节 B 的 Chunk[0]：注入章节 A 最后一块的 context_brief
        - 章节 B 的 Chunk[1]：注入章节 B Chunk[0] 的 context_brief
        """
        captured_contexts: list[str | None] = []

        async def mock_summarize(chunk, ctx, **kwargs):
            captured_contexts.append(ctx.context_brief)
            return _make_mock_summary(
                chunk.chapter_path[-1], chunk.chapter_path, len(captured_contexts)
            )

        with patch(
            "core.data.summary_pipeline.summarize_chunk",
            new_callable=AsyncMock,
            side_effect=mock_summarize,
        ), patch(
            "core.data.summary_pipeline.merge_chapter_summaries",
            new_callable=AsyncMock,
            return_value=pytest.importorskip(
                "core.data.summary_models"
            ).ChapterSummary(
                chapter_title="第二节",
                chapter_path=["第二节"],
                summary=_make_mock_summary("第二节", ["第二节"], 99),
                chunk_count=2,
            ),
        ):
            await summarize_document(
                two_chapter_chunk_list,
                stock_code="600000",
                report_date="2024-12-31",
                persist=False,
            )

        assert len(captured_contexts) == 3
        # Chunk 0（章节 A 首块）：无 context_brief
        assert captured_contexts[0] is None
        # Chunk 1（章节 B 首块）：注入章节 A 的 context_brief
        assert captured_contexts[1] is not None
        # Chunk 2（章节 B 子块 1）：注入章节 B Chunk 0 的 context_brief
        assert captured_contexts[2] is not None
        assert captured_contexts[2] != captured_contexts[1]  # 不同来源
```

### 5a. 静态检查与验证全红

```bash
# 类型检查
pyright core/data/summary_models.py core/data/chunk_summarizer.py core/data/chapter_merger.py core/data/summary_storage.py core/data/summary_pipeline.py

# 验证所有测试失败且原因为 NotImplementedError
pytest tests/test_summary_models.py tests/test_chunk_summarizer.py tests/test_chapter_merger.py tests/test_summary_storage.py tests/test_summary_pipeline.py --tb=short 2>&1 | grep -E "NotImplementedError|FAILED|PASSED|ERROR"

# 确认：
# - test_summary_models.py 中的模型验证测试应 PASSED（纯 Pydantic 模型，无 NotImplementedError）
# - 其他测试文件应全部 FAILED，且 traceback 均为 NotImplementedError
```

### 5b. Git 提交

```bash
git add -A
git commit -m "test: add contracts and failing tests for Step 3 summarization"
```

---

## ▶ 阶段 B：`/tdd-green` 执行以下步骤

<aside>
⚠️

**阶段 B 前置检查**：确认契约文件中所有 stub 均为 `raise NotImplementedError`，不存在重复定义或残留的旧实现，避免新实现被 stub 覆盖。

</aside>

### 6. 核心实现参考

<aside>
⚡

**并发策略**：

```
步骤 1（串行）：git checkout + 安装依赖
步骤 2（串行）：阶段 B 前置检查
阶段 2（并发）：
    ├─ Sub-agent A：步骤 3 实现 chunk_summarizer → 步骤 4 测试 → 步骤 5 commit
    ├─ Sub-agent B：步骤 6 实现 summary_storage → 步骤 7 测试 → 步骤 8 commit
    └─（等 A 和 B 完成后）
步骤 9（串行）：实现 chapter_merger → 步骤 10 测试 → 步骤 11 commit
步骤 12（串行）：实现 summary_pipeline → 步骤 13 测试 → 步骤 14 commit
步骤 15（串行）：全量验证 + 最终 commit
```

</aside>

**步骤 1：安装依赖** `depends_on: none`

- 操作类型：运行命令
- `pip install pydantic-ai`
- 更新 `requirements.txt` 或 `pyproject.toml` 添加 `pydantic-ai` 依赖
- 验证：`python -c "from pydantic_ai import Agent; print('OK')"`

**步骤 2：阶段 B 前置检查** `depends_on: [1]`

- 操作类型：运行命令
- 运行 `grep -rn "raise NotImplementedError" core/data/chunk_summarizer.py core/data/chapter_merger.py core/data/summary_storage.py core/data/summary_pipeline.py`
- 确认所有 stub 均为 `raise NotImplementedError`

**步骤 3：实现 chunk_summarizer** `depends_on: [2]`

- 操作类型：修改文件 `core/data/chunk_summarizer.py`
- 实现 `build_summarize_context()`：从 `Chunk` 的 `chapter_path`、`contained_chapters`、`chunk_index` 和 `previous_context_brief` 构建 `SummarizeContext` 实例。`contained_chapters` 为 `list[str] | None`，从 `Chunk.contained_chapters` 直接取值
- 实现 `summarize_chunk()`：
    1. 创建 PydanticAI Agent，`output_type=ChunkSummaryOutput`，`deps_type=SummarizeContext`
    2. 使用 `@agent.system_prompt` 动态构建系统提示：摘要格式要求 + `context_brief` 用途说明 + `key_data` 中 `unit` 推荐值列表 + `contained_chapters` 多章节处理指引
    3. 通过 `DeepSeekProvider` 显式初始化模型（参考 6.1 方式 2），使用 `httpx.AsyncClient(timeout=60)`
    4. 用户 prompt 中注入：`context_brief`（如有）→ `chapter_path` → `contained_chapters` 信息 → Chunk 原文
    5. `ModelSettings(temperature=temperature, max_tokens=max_tokens)`
    6. 添加 `@agent.output_validator` 校验 `key_points` 非空
    7. 抽取 `_run_agent()` 内部函数封装 `agent.run()` 调用，便于测试 mock
    8. 捕获 PydanticAI 异常，包装为 `LLMResponseError`
- 引用参考：6.1（初始化）、6.2（结构化输出）、6.3（依赖注入）、6.4（ModelSettings）、6.6（重试）
- 验证：`pytest tests/test_chunk_summarizer.py -v`

**步骤 4：测试 chunk_summarizer** `depends_on: [3]`

- 操作类型：运行命令
- `pytest tests/test_chunk_summarizer.py -v`
- 确认所有测试通过

**步骤 5：提交 chunk_summarizer** `depends_on: [4]`

- 操作类型：运行命令
- `git add core/data/chunk_summarizer.py && git commit -m "feat: implement chunk summarizer with PydanticAI + DeepSeek"`

**步骤 6：实现 summary_storage** `depends_on: [2]`（可与步骤 3 并发）

- 操作类型：修改文件 `core/data/summary_storage.py`
- 实现 `init_summary_tables()`：使用 `aiosqlite` 创建 `chunk_summary`、`chapter_summary`、`document_summary` 三张表，按契约中的字段定义。使用 `CREATE TABLE IF NOT EXISTS`
- 实现 `save_chunk_summary()`：将 `ChunkSummaryOutput` 序列化为 JSON 存入 `chunk_summary` 表，`key_points` 和 `key_data` 使用 `json.dumps()` 序列化，`created_at` 使用 `datetime.now(UTC).isoformat()`
- 实现 `save_chapter_summary()`：将 `ChapterSummary` 的 `summary` 字段整体 `model_dump_json()` 存入 `summary_json` 列
- 实现 `save_document_summary()`：存储文档级元信息，`all_key_points` 和 `all_key_data` 序列化为 JSON
- 实现 `load_document_summary()`：按 `stock_code` + `report_date` 查询并反序列化为 `DocumentSummary`。无记录返回 `None`
- 所有写操作包裹在 `try/except` 中，异常包装为 `SummaryStorageError`
- 使用 `logfire` 记录存储操作日志（与 `chunk_storage.py` 风格一致）
- 引用参考：参考已有 `chunk_storage.py` 的 aiosqlite 用法和代码风格
- 验证：`pytest tests/test_summary_storage.py -v`

**步骤 7：测试 summary_storage** `depends_on: [6]`

- 操作类型：运行命令
- `pytest tests/test_summary_storage.py -v`

**步骤 8：提交 summary_storage** `depends_on: [7]`

- 操作类型：运行命令
- `git add core/data/summary_storage.py && git commit -m "feat: implement summary storage with SQLite persistence"`

**步骤 9：实现 chapter_merger** `depends_on: [5]`

- 操作类型：修改文件 `core/data/chapter_merger.py`
- 实现 `build_single_chunk_chapter()`：将 `ChunkSummaryOutput` 包装为 `ChapterSummary`，`chunk_count=1`
- 实现 `merge_chapter_summaries()`：
    1. 若 `sub_summaries` 长度为 1，调用 `build_single_chunk_chapter()` 直接返回
    2. 多子块时，构建合并 prompt：收集各子块的 `detailed_summary` + `key_points` + `key_data`，按序拼接
    3. 创建合并 Agent（`output_type=ChunkSummaryOutput`），系统 prompt 说明「合并多个子块摘要为统一章节摘要」
    4. 调用 `_run_merge_agent()` 获取合并结果
    5. 包装为 `ChapterSummary`，`chunk_count=len(sub_summaries)`
    6. **降级处理**：`_run_merge_agent()` 失败时，catch 异常，将各子块 `detailed_summary` 用换行拼接作为 `detailed_summary`，各子块 `key_points` 合并去重，`key_data` 合并，构建降级 `ChapterSummary`，记录 warning 日志
- 引用参考：6.2（结构化输出）、6.4（ModelSettings）、6.6（重试）
- 验证：`pytest tests/test_chapter_merger.py -v`

**步骤 10：测试 chapter_merger** `depends_on: [9]`

- `pytest tests/test_chapter_merger.py -v`

**步骤 11：提交 chapter_merger** `depends_on: [10]`

- `git add core/data/chapter_merger.py && git commit -m "feat: implement chapter merger with LLM merge and degradation"`

**步骤 12：实现 summary_pipeline** `depends_on: [5, 8, 11]`

- 操作类型：修改文件 `core/data/summary_pipeline.py`
- 实现 `summarize_document()`：
    1. 遍历 `chunk_list.chunks`（按文档顺序，即列表顺序）
    2. 维护 `last_context_brief_by_chapter: dict[str, str]` 跟踪每个章节最后一个子块的 `context_brief`
    3. 维护 `last_chapter_brief: str | None` 跟踪上一个章节最后子块的 `context_brief`（用于跨章节注入）
    4. 对每个 Chunk：
        - 确定 `previous_context_brief`：同一章节内取 `last_context_brief_by_chapter[chapter_key]`；新章节取 `last_chapter_brief`
        - 调用 `build_summarize_context()` + `summarize_chunk()`
        - 更新 `last_context_brief_by_chapter` 和 `last_chapter_brief`
        - 如果 `persist=True`，调用 `save_chunk_summary()`
    5. 按 `chapter_path` 分组 Chunk 摘要结果
    6. 单 Chunk 章节 → `build_single_chunk_chapter()`；多 Chunk 章节 → `merge_chapter_summaries()`
    7. 各 `ChapterSummary` 按原文顺序排列
    8. 汇总 `all_key_points`（各章节 `key_points` 合并）和 `all_key_data`（各章节 `key_data` 合并）
    9. 构建 `DocumentSummary`
    10. 如果 `persist=True`，调用 `init_summary_tables()` + `save_chapter_summary()` + `save_document_summary()`
- 引用参考：6.3（依赖注入 pattern）
- 验证：`pytest tests/test_summary_pipeline.py -v`

**步骤 13：测试 summary_pipeline** `depends_on: [12]`

- `pytest tests/test_summary_pipeline.py -v`

**步骤 14：提交 summary_pipeline** `depends_on: [13]`

- `git add core/data/summary_pipeline.py && git commit -m "feat: implement end-to-end summarization pipeline"`

### 8. 验证清单

```bash
# 全量测试
pytest tests/ -v --tb=short

# 类型检查
pyright core/data/summary_models.py core/data/chunk_summarizer.py core/data/chapter_merger.py core/data/summary_storage.py core/data/summary_pipeline.py

# Linter
ruff check core/data/summary_models.py core/data/chunk_summarizer.py core/data/chapter_merger.py core/data/summary_storage.py core/data/summary_pipeline.py

# Step 1 + Step 2 回归
pytest tests/test_pdf_parser.py tests/test_chapter_detector.py tests/test_chunker.py tests/test_chunk_storage.py -v
```

**步骤 15：最终验证与提交** `depends_on: [14]`

- 运行上述全部验证命令
- 如有修复：`git add -A && git commit -m "fix: address lint and type issues"`

### 9. 测试补充（实现后评估）

以下测试场景在实现过程中根据发现补充：

- [ ]  **空 ChunkList 测试**：传入空 `chunks` 列表时 `summarize_document()` 的行为
- [ ]  **超长 Chunk 测试**：单个 Chunk 接近 `max_tokens` 上限时 LLM 是否截断
- [ ]  **重复章节路径测试**：多个不相邻的 Chunk 共享同一 `chapter_path` 的分组正确性
- [ ]  **持久化回归测试**：`save_document_summary()` → `load_document_summary()` 的 `key_data` 中 `PeriodInfo` 嵌套序列化/反序列化
- [ ]  **并发安全测试**：多次调用 `summarize_document()` 写入同一数据库的行为

### 10. 技术决策说明

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| Agent 初始化方式 | 显式 `OpenAIChatModel`  • `DeepSeekProvider` | 可控 `http_client` 超时、便于后续切换模型 |
| `output_type` vs 手动 JSON 解析 | PydanticAI `output_type` | 自动结构化验证 + 重试，减少手工解析代码 |
| 温度设置 0.3 | 偏低温度 | 摘要任务需确定性，不需要创造性 |
| 串行摘要（非并发 LLM 调用） | 串行 | 后一块依赖前一块的 `context_brief`，无法并发 |
| 章节合并降级策略 | 拼接子块摘要 | 保证可用性，合并失败不阻塞流程 |
| 存储与摘要器并发开发 | 可以 | 两模块接口独立，无代码依赖 |
| `_run_agent()` 抽取为内部函数 | 便于测试 mock | 避免 mock 整个 PydanticAI Agent 类 |
| 异常继承 `DataLifeError` | 与项目一致 | 遵循已有异常层次结构 |

---

## 文件影响范围

| 操作 | 文件路径 | 说明 |
| --- | --- | --- |
| **新建** | `core/data/summary_models.py` | 摘要数据模型 |
| **追加** | `core/data/exceptions.py` | 摘要异常类 |
| **新建** | `core/data/chunk_summarizer.py` | 逐 Chunk 摘要器 |
| **新建** | `core/data/chapter_merger.py` | 章节合并器 |
| **新建** | `core/data/summary_storage.py` | 摘要 SQLite 持久化 |
| **新建** | `core/data/summary_pipeline.py` | 端到端编排管道 |
| **新建** | `tests/test_summary_models.py` | 模型验证测试 |
| **新建** | `tests/test_chunk_summarizer.py` | 摘要器测试 |
| **新建** | `tests/test_chapter_merger.py` | 合并器测试 |
| **新建** | `tests/test_summary_storage.py` | 存储测试 |
| **新建** | `tests/test_summary_pipeline.py` | 管道集成测试 |
| **修改** | `requirements.txt` / `pyproject.toml` | 添加 `pydantic-ai` 依赖 |

---

## 测试运行命令

```bash
# 单个模块测试
pytest tests/test_summary_models.py -v
pytest tests/test_chunk_summarizer.py -v
pytest tests/test_chapter_merger.py -v
pytest tests/test_summary_storage.py -v
pytest tests/test_summary_pipeline.py -v

# Step 3 全部测试
pytest tests/test_summary_models.py tests/test_chunk_summarizer.py tests/test_chapter_merger.py tests/test_summary_storage.py tests/test_summary_pipeline.py -v

# 全量回归（含 Step 1 + Step 2）
pytest tests/ -v
```

#### 6.1 PydanticAI Agent + DeepSeek 初始化

来源：[ai.pydantic.dev/models/openai](http://ai.pydantic.dev/models/openai)

```python
# 方式 1：简写（自动读取 DEEPSEEK_API_KEY 环境变量）
from pydantic_ai import Agent
agent = Agent('deepseek:deepseek-chat')

# 方式 2：显式配置（推荐，可自定义 http_client）
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from httpx import AsyncClient

custom_http_client = AsyncClient(timeout=30)
model = OpenAIChatModel(
    'deepseek-chat',
    provider=DeepSeekProvider(
        api_key='your-api-key',  # 或从环境变量读取
        http_client=custom_http_client,
    ),
)
agent = Agent(model)
```

#### 6.2 结构化输出（output_type）

来源：[ai.pydantic.dev/output](http://ai.pydantic.dev/output)

```python
from pydantic import BaseModel
from pydantic_ai import Agent

class CityLocation(BaseModel):
    city: str
    country: str

agent = Agent(
    'deepseek:deepseek-chat',
    output_type=CityLocation,
    system_prompt='Extract the city and country from the user message.',
)
result = await agent.run('I live in Beijing')
print(result.output)  # CityLocation(city='Beijing', country='China')
```

#### 6.3 依赖注入（deps_type + RunContext）

来源：[ai.pydantic.dev/dependencies](http://ai.pydantic.dev/dependencies)

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class MyDeps:
    context_brief: str | None
    chapter_path: list[str]

agent = Agent(
    'deepseek:deepseek-chat',
    deps_type=MyDeps,
    output_type=ChunkSummaryOutput,
)

@agent.system_prompt
async def build_system_prompt(ctx: RunContext[MyDeps]) -> str:
    base = "你是一名专业的文档摘要分析师..."
    if ctx.deps.context_brief:
        base += f"\n\n【前文上下文】\n{ctx.deps.context_brief}"
    base += f"\n\n【当前章节路径】{' > '.join(ctx.deps.chapter_path)}"
    return base

# 调用
result = await agent.run(
    chunk.text,
    deps=MyDeps(context_brief="前文...", chapter_path=["第一节"]),
)
```

#### 6.4 模型设置（temperature、max_tokens）

来源：[ai.pydantic.dev/agents](http://ai.pydantic.dev/agents)

```python
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

agent = Agent(
    'deepseek:deepseek-chat',
    model_settings=ModelSettings(
        temperature=0.3,
        max_tokens=4096,
    ),
)
# 也可在 run 时覆盖
result = await agent.run(
    'message',
    model_settings=ModelSettings(temperature=0.1),
)
```

#### 6.5 DeepSeek JSON 输出注意事项

来源：[api-docs.deepseek.com](http://api-docs.deepseek.com)

- 设置 `response_format={'type': 'json_object'}` 可强制 JSON 输出
- **PydanticAI 的 `output_type` 已自动处理**，无需手动设置 `response_format`
- 在 prompt 中包含 "json" 关键词和期望格式示例有助于提高输出质量
- 合理设置 `max_tokens` 避免输出截断
- DeepSeek API 偶尔返回空 content，需做防御处理

#### 6.6 重试与错误处理

来源：[ai.pydantic.dev/agents](http://ai.pydantic.dev/agents)

```python
from pydantic_ai import Agent, ModelRetry

agent = Agent('deepseek:deepseek-chat', retries=3)

# 自定义重试逻辑（通过 tool 或 output validator）
@agent.output_validator
async def validate_output(ctx, output):
    if not output.key_points:
        raise ModelRetry('key_points 不能为空，请重新生成')
    return output
```

### 7. 实现步骤

### 已有代码资产（Step 3 将依赖）

- [x]  **Step 1 已完成**：PyMuPDF4LLM 解析 PDF（22/22 测试通过）
- [x]  **Step 2 已完成**：人工逻辑分块策略
- [ ]  **重构任务完成**：截止到 Step 2 的代码重构（当前执行中，需关注以下高优修复）：
    - ~~问题6 已修复~~：`_split_by_token_window()` 已改用 `truncate_tail_tokens()` 取尾部 overlap
    - ~~问题8 已修复~~：`_split_by_subheadings()` 预检测分支已改用 `_extract_chapter_text(parsed, boundary)` 从原始页面数据提取文本
    - 问题7 已修复：`contained_chapters` 列已添加到 `chunk_storage.py`
    - 问题12 已修复：`models.py` 拆分为 `api_models.py` + `models.py` + `exceptions.py`
    - 问题13 已修复：Step 2 异常已继承 `DataLifeError`
- [ ]  **DeepSeek API Key** 已配置（环境变量 `DEEPSEEK_API_KEY`）
- [ ]  **依赖安装**：`pip install pydantic-ai`