# 执行计划：Step 2 代码重构与质量修复

## 1. 重构目标

基于质量审计报告，修复 Step 2（人工逻辑分块策略）代码中的 **3 个功能性/数据 bug**（问题 6、7、8），补充关键模块的测试覆盖，清理死代码与架构异味，确保 Step 3 摘要管线可正确消费 ChunkList。

---

## 2. 重构评估报告

已通过 GitHub API 逐一验证审计报告（15 个问题），**全部确认属实**。

### 验证结论

| 🔴 **高优先级** | **验证状态** | **代码定位** |
| --- | --- | --- |
| 问题 6：overlap 取首部而非尾部 | ✅ 确认 | `chunker.py` → `_split_by_token_window()` 第 ~280 行 |
| 问题 7：contained_chapters 持久化丢失 | ✅ 确认 | `chunk_storage.py` → `chunk_meta` 表缺少列 |
| 问题 8：子章节文本用段落索引代替页码 | ✅ 确认 | `chunker.py` → `_split_by_subheadings()` 预检测边界分支 |
| 问题 2：TocPageStrategy 零测试覆盖 | ✅ 确认 | `test_chapter_detector.py` 无 TestTocPageStrategy 类 |

| 🟡 **中优先级** | **验证状态** |
| --- | --- |
| 问题 1：`_merge_same_page_boundaries()` 死代码 | ✅ 确认 — `return result` 后残留整段旧实现，返回类型不同 |
| 问题 9：UNIQUE 约束语义错误 | ✅ 确认 — `UNIQUE(stock_code, report_date, page_start, page_end)` 会冲突 |
| 问题 12：[models.py](http://models.py) 职责过载 | ✅ 确认 — Pydantic + dataclass + 异常 + 别名混合 |
| 问题 13：异常不继承 DataLifeError | ✅ 确认 — `ChunkingError(Exception)` 绕过项目基类 |
| 问题 3/4/5：测试边界/深度不足 | ✅ 确认 |

| 🟢 **低优先级** | **验证状态** |
| --- | --- |
| 问题 10：`_get_encoder` 死导入 | ✅ 确认 |
| 问题 11：`dataclasses` 导入位于文件中部 | ✅ 确认 |
| 问题 14：MergedChapter 定义在 [chunker.py](http://chunker.py) | ✅ 确认 |
| 问题 15：logical_[chunker.py](http://chunker.py) 命名易混淆 | ✅ 确认 |

### 影响范围

- **直接修改**：`chunker.py`、`chunk_storage.py`、`models.py`、`logical_chunker.py`、`token_counter.py`
- **间接影响**（导入路径变更）：`test_chunker.py`、`test_chunk_storage.py`、`test_chapter_detector.py`、所有引用 `logical_chunker` 和 `models` 的模块
- **高风险变更**：问题 8 涉及 `_split_by_subheadings()` 的核心文本提取逻辑改动

---

## 3. 前置条件

- `master` 分支最新代码
- Python 环境已安装：`pymupdf`、`tiktoken`、`aiosqlite`、`logfire`、`pytest`、`pytest-asyncio`
- 所有现有测试通过（`pytest tests/`）

---

## 4. Git 准备

```bash
git checkout master
git pull origin master
git checkout -b refactor/step2-quality-fixes
```

---

## 5. 测试补充

<aside>
🛡️

**铁律**：所有测试补充必须在重构前完成并通过，作为行为守恒的基准线。

</aside>

### 步骤 T1：补充 TocPageStrategy 独立测试

- **目标文件**：`tests/test_chapter_detector.py`
- **新增测试类**：`TestTocPageStrategy`
- **覆盖场景**：
    - 正常目录页（含页码列表）→ 返回正确章节边界
    - 目录页页码偏移（目录页自身页码 vs 内容页码）→ 验证偏移计算
    - 格式异常的目录页（缺少页码、非标准分隔符）→ 返回 None 降级
    - 多级目录页 → 验证 level 推断
- **depends_on**: none
- **验证**：`pytest tests/test_chapter_detector.py -v` 全部通过
- **提交**：`test: add independent tests for TocPageStrategy`

### 步骤 T2：补充 chapter_detector 异常路径测试

- **目标文件**：`tests/test_chapter_detector.py`
- **新增场景**（在 `TestBookmarkStrategy` 和 `TestDetectChapters` 中扩展）：
    - 书签页码越界（指向不存在的页面）
    - 单页文档
    - 空文档（0 页）
    - 书签标题与实际页面文本不匹配
- **depends_on**: none
- **验证**：`pytest tests/test_chapter_detector.py -v` 全部通过
- **提交**：`test: add boundary and exception tests for chapter_detector`

### 步骤 T3：补充 chunk_storage 深度测试

- **目标文件**：`tests/test_chunk_storage.py`
- **新增场景**：
    - 覆盖写入（同一 stock_code + report_date 保存两次）→ 验证幂等性，第二次写入覆盖第一次
    - `chapter_path` 列表的序列化/反序列化 round-trip
    - DB 文件不存在时 `load_chunks` 的行为 → 预期返回 None 或抛异常
    - 构造包含 `contained_chapters` 的 `Chunk` → 验证当前丢失行为（为后续修复提供回归基准）
- **depends_on**: none
- **验证**：`pytest tests/test_chunk_storage.py -v` 全部通过
- **提交**：`test: add overwrite, serialization, and edge case tests for chunk_storage`

### 步骤 T4：补充 _clean_markdown 边界测试

- **目标文件**：`tests/test_pdf_parser.py`
- **新增场景**：
    - 带前后空格的数字行 → 应被移除
    - 多位数页码（如   `123`  ）→ 应被移除
    - 数字行夹在正文段落之间（如财务表格中的独立数字）→ 验证是否误删
    - 空字符串输入
- **depends_on**: none
- **验证**：`pytest tests/test_pdf_parser.py -v` 全部通过
- **提交**：`test: add boundary tests for _clean_markdown`

### 步骤 T5：补充 overlap 行为测试

- **目标文件**：`tests/test_chunker.py`
- **新增场景**：
    - 构造超长文本 → 触发 `_split_by_token_window` → 验证第二个 chunk 的 overlap 文本来自前一个 chunk 的 **尾部**（当前测试会失败，标记为 `@pytest.mark.xfail`，修复后移除标记）
- **depends_on**: none
- **验证**：`pytest tests/test_chunker.py -v`（overlap 测试预期 xfail）
- **提交**：`test: add overlap direction verification test (xfail before fix)`

<aside>
⚡

**并发执行**：T1、T2、T3、T4、T5 操作不同测试文件/类，可通过 sub-agent 并行执行。

</aside>

---

## 6. 重构步骤

### 阶段 A：Bug 修复（高优先级）

#### 步骤 R1：修复 overlap 方向（问题 6）

- **重构手法**：提取函数 + 修改逻辑
- **目标文件**：`core/data/token_counter.py`、`core/data/chunker.py`
- **描述**：在 `token_counter.py` 中新增 `truncate_tail_tokens(text, max_tokens)` 函数，取文本**尾部** N 个 token。在 `chunker.py` 的 `_split_by_token_window()` 中，将 overlap 获取逻辑从 `truncate_to_tokens(prev_text, overlap_tokens)` 改为调用 `truncate_tail_tokens(prev_text, overlap_tokens)`。
- **depends_on**: T5
- **验证**：`pytest tests/test_chunker.py tests/test_token_counter.py -v` 全部通过，移除 T5 中 overlap 测试的 xfail 标记
- **提交**：`refactor: fix overlap direction - take tail tokens instead of head`

#### 步骤 R2：修复 contained_chapters 持久化（问题 7）

- **重构手法**：扩展 schema + 修改序列化/反序列化
- **目标文件**：`core/data/chunk_storage.py`
- **描述**：在 `chunk_meta` 表中新增 `contained_chapters TEXT` 列。`save_chunks()` 中将 `chunk.contained_chapters` 序列化为 JSON 字符串写入该列。`load_chunks()` 中从该列反序列化恢复为 `list[ChunkMeta]`，赋给 Chunk 的 `contained_chapters` 属性。同时修复 UNIQUE 约束（问题 9）为 `UNIQUE(stock_code, report_date, chunk_index)`。
- **depends_on**: T3
- **验证**：`pytest tests/test_chunk_storage.py -v` 全部通过，更新 T3 中 contained_chapters round-trip 测试从 xfail 改为正常断言
- **提交**：`refactor: persist contained_chapters and fix UNIQUE constraint`

#### 步骤 R3：修复子章节文本提取逻辑（问题 8）

- **重构手法**：修改逻辑 + 调整函数签名
- **目标文件**：`core/data/chunker.py`
- **描述**：修改 `_split_by_subheadings()` 的预检测边界分支。当使用 `sub_boundaries` 时，不再将拼接后的 `text` 按 `\n\n` split 再用页码索引访问段落数组。改为：接收 `parsed: ParsedDocument` 参数，直接调用 `_extract_chapter_text(parsed, boundary)` 从原始页面数据中提取每个子边界范围的文本。相应地更新 `build_chunks()` 中调用 `_split_by_subheadings()` 的地方，传入 `parsed` 参数。
- **depends_on**: T5（确保现有 chunker 测试基准稳定）
- **验证**：`pytest tests/test_chunker.py -v` 全部通过
- **提交**：`refactor: fix subheading split to use page data instead of paragraph index`

<aside>
⚡

**并发策略**：R1 和 R2 操作不同文件，可并发。R3 与 R1 都修改 `chunker.py`，**必须串行**（R1 先完成后再执行 R3）。

</aside>

### 阶段 B：代码清理（中低优先级）

#### 步骤 R4：清理 [chunker.py](http://chunker.py) 死代码与导入问题（问题 1、10、11）

- **重构手法**：删除死代码 + 移除死导入 + 移动导入
- **目标文件**：`core/data/chunker.py`
- **描述**：
    1. 删除 `_merge_same_page_boundaries()` 中 `return result` 之后的所有死代码（旧版返回 `list[ChapterBoundary]` 的实现）
    2. 从导入语句中移除 `_get_encoder`
    3. 将 `from dataclasses import dataclass` 移动到文件顶部导入区域
- **depends_on**: R1, R3（[chunker.py](http://chunker.py) 的 bug 修复全部完成后再清理）
- **验证**：`pytest tests/test_chunker.py -v` 全部通过
- **提交**：`refactor: cleanup - remove dead code, unused import, fix import order in chunker.py`

#### 步骤 R5：修复异常继承体系（问题 13）

- **重构手法**：修改继承关系
- **目标文件**：`core/data/models.py`
- **描述**：将 `ChunkingError` 的基类从 `Exception` 改为 `DataLifeError`（从 `core.exceptions` 导入）。保留 `ChunkingError` 的子类 `EmptyDocumentError`、`ChapterDetectionError`、`StorageError` 的继承关系不变（它们仍继承 `ChunkingError`，间接继承 `DataLifeError`）。确保 `ChunkingError.__init__` 的签名与 `DataLifeError.__init__` 兼容（接受 `message` 和可选 `cause` 参数）。
- **depends_on**: none
- **验证**：`pytest tests/ -v` 全部通过
- **提交**：`refactor: make ChunkingError inherit from DataLifeError`

#### 步骤 R6：移动 MergedChapter 到 [models.py](http://models.py)（问题 14）

- **重构手法**：移动类
- **目标文件**：`core/data/models.py`、`core/data/chunker.py`
- **描述**：将 `MergedChapter` dataclass 定义从 `chunker.py` 移至 `models.py`。在 `chunker.py` 中添加 `from core.data.models import MergedChapter` 导入。
- **depends_on**: R4（[chunker.py](http://chunker.py) 清理完成后再移动，避免冲突）
- **验证**：`pytest tests/test_chunker.py -v` 全部通过
- **提交**：`refactor: move MergedChapter to models.py`

#### 步骤 R7：拆分 [models.py](http://models.py)（问题 12）

- **重构手法**：提取模块
- **目标文件**：`core/data/models.py` → `core/data/api_models.py` + `core/data/exceptions.py`
- **描述**：
    1. 将 Pydantic 外部 API 模型（`StockItem`、`StockListResponse`、`AnnouncementItem`、`AnnouncementsResponse`）提取到 `core/data/api_models.py`
    2. 将异常类（`ChunkingError` 及其子类）提取到 `core/data/exceptions.py`
    3. `models.py` 保留内部领域 dataclass 和类型别名
    4. 更新所有引用这些类的导入路径（搜索 `from core.data.models import` 定位所有调用方）
- **depends_on**: R5, R6（异常继承修复和 MergedChapter 移动完成后再拆分）
- **验证**：`pytest tests/ -v` 全部通过
- **提交**：`refactor: extract api_models.py and exceptions.py from models.py`

#### 步骤 R8：重命名 logical_[chunker.py](http://chunker.py)（问题 15）

- **重构手法**：重命名模块
- **目标文件**：`core/data/logical_chunker.py` → `core/data/chunk_pipeline.py`
- **描述**：将 `logical_chunker.py` 重命名为 `chunk_pipeline.py`，更新所有引用该模块的导入路径。保持内部函数签名和行为不变。
- **depends_on**: R7（[models.py](http://models.py) 拆分完成后再重命名，避免多文件同时变动引发混乱）
- **验证**：`pytest tests/ -v` 全部通过
- **提交**：`refactor: rename logical_chunker.py to chunk_pipeline.py`

---

## 7. 接口变更说明

| **变更** | **影响范围** | **迁移方式** |
| --- | --- | --- |
| `token_counter.py` 新增 `truncate_tail_tokens()` | 仅 `chunker.py` 内部调用 | 新增函数，无破坏性 |
| `_split_by_subheadings()` 新增 `parsed` 参数 | 仅 `build_chunks()` 内部调用 | 私有函数，无外部影响 |
| `chunk_meta` 表新增 `contained_chapters` 列 | 已有 DB 文件需要 migration 或重建 | 使用 `ALTER TABLE` 添加列，或清空重跑 |
| `chunk_meta` 表 UNIQUE 约束变更 | 已有 DB 文件 | 需重建表（SQLite 不支持 ALTER CONSTRAINT） |
| `ChunkingError` 基类变更 | 所有 `except ChunkingError` 调用方 | 向上兼容，`except DataLifeError` 也能捕获 |
| 模块路径变更（`api_models.py`、`exceptions.py`、`chunk_pipeline.py`） | 所有引用旧路径的 import | 更新 import 语句 |

---

## 8. 验证清单

- [ ]  所有测试通过：`pytest tests/ -v`
- [ ]  类型检查通过（如有）：`basedpyright core/data/`
- [ ]  overlap 测试确认取尾部 token
- [ ]  contained_chapters save → load round-trip 验证
- [ ]  子章节文本提取使用原始页面数据而非段落数组
- [ ]  `ChunkingError` 可被 `except DataLifeError` 捕获
- [ ]  `from core.data.chunk_pipeline import chunk_document` 正常工作
- [ ]  `from core.data.api_models import StockItem` 正常工作
- [ ]  `from core.data.exceptions import ChunkingError` 正常工作
- [ ]  无死代码、死导入残留

---

## 9. 重构决策说明

### 执行顺序的考量

- **Bug 修复优先于代码清理**：问题 6、7、8 直接影响 Step 3 的功能正确性，必须首先解决
- **测试先行**：所有重构步骤前先补充测试基准线，确保行为守恒可验证
- [**chunker.py](http://chunker.py) 变更串行**：R1 → R3 → R4 → R6 按顺序执行，避免同一文件并发修改产生冲突

### 问题 8 的修复方案选择

选择传入 `ParsedDocument` 而非尝试修复段落索引映射，原因：

- 页面文本内部的 `\n\n` 数量不确定，无法可靠地从拼接后文本反向定位页面边界
- `_extract_chapter_text()` 已经实现了从 `ParsedDocument` 按页码范围提取文本的逻辑，可直接复用
- Trade-off：增加了 `_split_by_subheadings()` 的参数，但该函数为私有函数，影响可控

### 问题 12 拆分粒度

选择拆分为 3 个文件而非更细粒度，原因：

- 当前 Step 2 的模型数量有限，过度拆分反而增加导入复杂度
- 按「外部 API / 内部领域 / 异常」三类划分，边界清晰且与项目现有 `core/exceptions.py` 对齐

### 未纳入执行计划的建议

- 问题 5（`_clean_markdown` 边界测试）：已纳入测试补充阶段（T4），但不涉及代码重构
- 问题 3（chapter_detector 异常路径测试）：已纳入测试补充阶段（T2），但不涉及代码重构

---

## 依赖关系图

```mermaid
graph TD
    T1["T1: TocPageStrategy 测试"] --> |none| DONE_T["测试基准线就绪"]
    T2["T2: chapter_detector 异常测试"] --> |none| DONE_T
    T3["T3: chunk_storage 深度测试"] --> |none| DONE_T
    T4["T4: _clean_markdown 边界测试"] --> |none| DONE_T
    T5["T5: overlap 行为测试"] --> |none| DONE_T

    DONE_T --> R1["R1: 修复 overlap 方向"]
    DONE_T --> R2["R2: 修复 contained_chapters + UNIQUE"]
    DONE_T --> R5["R5: 异常继承修复"]

    R1 --> R3["R3: 修复子章节文本提取"]
    R3 --> R4["R4: 清理 chunker.py 死代码"]
    R4 --> R6["R6: 移动 MergedChapter"]
    R5 --> R7["R7: 拆分 models.py"]
    R6 --> R7
    R7 --> R8["R8: 重命名 logical_chunker"]

    R2 --> DONE_R["集成验证"]
    R8 --> DONE_R
```

---

## 并发执行总览

```
阶段 0（并发）：测试补充
    ├─ Sub-agent A：T1 TocPageStrategy 测试
    ├─ Sub-agent B：T2 异常路径测试
    ├─ Sub-agent C：T3 chunk_storage 深度测试
    ├─ Sub-agent D：T4 _clean_markdown 边界测试
    └─ Sub-agent E：T5 overlap 行为测试
    → git commit × 5

阶段 1（并发）：Bug 修复
    ├─ Sub-agent A：R1 overlap 方向修复（chunker.py + token_counter.py）
    ├─ Sub-agent B：R2 contained_chapters + UNIQUE（chunk_storage.py）
    └─ Sub-agent C：R5 异常继承（models.py）
    → git commit × 3

阶段 2（串行）：chunker.py 后续修复
    R3 子章节文本提取 → commit
    R4 死代码清理 → commit
    R6 MergedChapter 移动 → commit

阶段 3（串行）：架构调整
    R7 models.py 拆分 → commit
    R8 logical_chunker 重命名 → commit

阶段 4（串行）：集成验证
    pytest tests/ -v → 全量通过
```