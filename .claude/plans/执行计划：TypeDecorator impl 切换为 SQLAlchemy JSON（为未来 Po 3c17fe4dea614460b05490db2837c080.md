# 执行计划：TypeDecorator impl 切换为 SQLAlchemy JSON（为未来 PostgreSQL 迁移准备）

## 模式

**模式 A：代码重构（Refactor）**

## 重构目标

将现有自定义 JSON TypeDecorator 的底层存储类型从 `Text` 统一切换为 SQLAlchemy `JSON`，在不改变外部行为与现有数据兼容性的前提下，为未来迁移到 PostgreSQL（优先 JSONB）打基础。

## 重构评估报告

### 当前结构概览

- 已存在的 4 个 TypeDecorator（示例）：`JsonStringList`、`JsonChunkMetaList`、`JsonKeyDataItemList`、`JsonPydanticModel`。
- 当前实现以 `Text` 作为 `impl`，并在 `process_bind_param` / `process_result_value` 中做 `json.dumps` / `json.loads` 或对象构造。

### 主要问题与风险点

1. **重复序列化风险**
    - 若 `impl` 切换为 `JSON` 后仍执行 `json.dumps`，可能出现“字符串再被 JSON 编码”的双重编码。
2. **跨方言行为差异风险**
    - SQLite 下 `JSON` 仍可能落到 TEXT 存储，但 PG 下 `JSON/JSONB` 会启用原生 JSON 绑定与返回行为。
3. **对象转换边界需要明确**
    - `TypeDecorator` 的职责应聚焦为：
        - 绑定参数时：把领域对象转换为“JSON 可序列化的 Python 结构”（dict/list/str/int/float/bool/None）。
        - 结果取回时：把“Python 结构”转换回领域对象（dataclass / Pydantic）。

### 影响范围

- 直接修改：自定义 TypeDecorator 定义文件（例如 `core/db/types.py`）。
- 间接影响：所有使用这些列类型的 ORM 模型字段定义（例如 `core/db/models.py`）与其调用方（storage 模块）。

## 前置条件

- 当前测试套件可运行且稳定。
- 已确认这些字段在 SQL 层不会依赖字符串匹配（例如对 JSON 文本做 LIKE）。

## Git 准备

```bash
git checkout main && git pull origin main
git checkout -b refactor/orm-json-impl-json
```

## 测试补充（建议）

为确保 SQLite 与 PG 方言差异下的行为守恒，补充或强化以下测试（只测行为，不测实现）：

1. **TypeDecorator round-trip 行为**
    - 输入领域对象 → 写入 → 读出 → 与原对象等价。
    - 覆盖：None、空列表、嵌套对象、包含 `tuple` 的字段。
2. **storage 层 save/load 行为**
    - 确认 storage 不再传入已序列化字符串。
3. **数据库兼容性基线**
    - 在 SQLite 上跑全量测试作为基线。
    - 如果 CI 有条件，增加一条 PG（JSONB）环境的测试矩阵。

## 重构步骤

### 步骤 1 — Git 分支创建

- **操作类型**：Git 操作
- **重构手法**：N/A
- **目标文件**：N/A
- **描述**：从 main 拉取最新代码并创建分支 `refactor/orm-json-impl-json`
- `depends_on: none`

### 步骤 2 — 校验现有测试基线

- **操作类型**：校验
- **重构手法**：N/A
- **目标文件**：N/A
- **描述**：在任何改动前运行全量测试，记录当前基线必须全绿
- `depends_on: [1]`

### 步骤 3 — 调整 TypeDecorator 的 JSON 边界

- **操作类型**：重构操作
- **重构手法**：Replace Type
- **目标文件**：`core/db/types.py`（或当前 TypeDecorator 所在文件）
- **描述**：
    - 将所有自定义 JSON TypeDecorator 的 `impl` 从 `Text` 统一改为 `JSON`。
    - 绑定参数阶段：不再返回 JSON 字符串，改为返回 JSON 可序列化的 Python 结构（dict/list/原子类型）。
    - 结果取回阶段：从 Python 结构恢复领域对象；保持与当前 storage/业务侧看到的运行时类型一致。
    - 明确处理 `None` 透传。
- `depends_on: [2]`

### 步骤 4 — 校验 + 提交 TypeDecorator 修改

- **操作类型**：校验 + Git 操作
- **重构手法**：N/A
- **目标文件**：N/A
- **描述**：运行 TypeDecorator 单测与全量测试，全部通过后提交
- `depends_on: [3]`

### 步骤 5 — 适配 ORM 模型字段声明（如需要）

- **操作类型**：重构操作
- **重构手法**：Replace Type
- **目标文件**：`core/db/models.py`
- **描述**：
    - 确认所有 JSON 字段仍引用这些 TypeDecorator。
    - 保持 `Mapped[...]` 的语义类型不回退为 `Any` 或 `dict`。
- `depends_on: [4]`

### 步骤 6 — 校验 + 提交 ORM 模型修改

- **操作类型**：校验 + Git 操作
- **重构手法**：N/A
- **目标文件**：N/A
- **描述**：运行全量测试确认无回归后提交
- `depends_on: [5]`

### 步骤 7 — storage 层双重编码排查（如存在）

- **操作类型**：重构操作
- **重构手法**：Remove Dead Code
- **目标文件**：`core/data/chunk_storage.py`、`core/data/summary_storage.py`
- **描述**：
    - 确保 storage 层传递的是领域对象或 Python 结构，而不是 JSON 字符串。
    - 移除任何遗留的 `json.dumps/json.loads` 逻辑，避免与 `JSON` impl 叠加。
- `depends_on: [4]`

### 步骤 8 — 校验 + 提交 storage 清理

- **操作类型**：校验 + Git 操作
- **重构手法**：N/A
- **目标文件**：N/A
- **描述**：全量测试通过后提交
- `depends_on: [7]`

### 步骤 9 — 整体验证

- **操作类型**：校验
- **重构手法**：N/A
- **目标文件**：N/A
- **描述**：运行全量测试 + 类型检查 + linter，确认无回归
- `depends_on: [6, 8]`

## 接口变更说明

- ORM 字段对业务侧暴露的运行时类型不变（仍是 `list[str]`、`list[ChunkMeta]`、`ChunkSummaryOutput` 等）。
- TypeDecorator 的内部“中间表示”从 JSON 字符串改为 Python 结构（dict/list），避免方言差异下的双重编码。

## 验证清单

- [ ]  TypeDecorator round-trip 测试全部通过
- [ ]  storage save→load round-trip 测试全部通过
- [ ]  全量 `pytest` 通过
- [ ]  类型检查通过
- [ ]  linter 通过
- [ ]  SQLite 数据兼容：旧数据可读，新写入格式不引入双重编码

## 重构决策说明

- 选择 `JSON + TypeDecorator` 的核心目的是为 PG 迁移铺路：未来切换到 PG 时可自然落到原生 JSON/JSONB 绑定与查询能力。
- TypeDecorator 仍然必要：它负责把 `dict/list` 提升为领域对象（dataclass/Pydantic），这是纯 `JSON` 类型本身不提供的。
- trade-off：在 SQLite 上收益主要是语义统一与迁移准备，性能与存储收益有限。