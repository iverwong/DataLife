# 优化方案：token ID 池化 + pipeline 编排重构

<aside>
📋

本方案是对原始执行计划的架构级优化，核心变更：**逐页编码 + token ID 池化**，消除 pipeline 中的重复编码，修复 page_range 不精确问题。同时移除 TextSegment 中间层，直通路径直接产出 Chunk。

</aside>

---

## 背景与动机

原始计划中存在以下效率问题：

1. **重复编码**：`count_tokens(parsed.full_text)` 全量编码 1 次 → `split_text_by_token_window` 内 `slice_tokens` 每个窗口再全量编码 1 次 → 总计 N+1 次全量 encode
2. **全量拼接浪费**：`parsed.full_text` 是 `@property`，每次访问都 `"\n\n".join()` 全量拼接
3. **page_range 不精确**：直通路径硬编码 `page_range=(1, page_count)`，下游无法定位具体页码
4. **正常路径同样浪费**：`build_chunks` → `count_tokens(chapter_text)` 逐章编码，`_split_by_token_window` → `slice_tokens` 逐窗口重复编码，`ChunkBuilder.create_chunk` 内部再次 `count_tokens(text)`

### 优化核心思路

将「逐页编码」提升为 pipeline 的第一步，产出共享的 token ID 池（`array.array('I')`），后续所有步骤从池中取数据，**全程零重复编码**。

---

## 核心设计

### 新模块：`core/data/token_indexer.py`

独立模块，职责：逐页编码 + token ID 池管理 + 页码边界查找。

依赖关系：`token_indexer` → `token_counter`（公开的 `get_encoder`）+ `models`（`ParsedDocument`）

### Pipeline 编排变更

```
旧流程：
Step 1: Open PDF
Step 2: count_tokens(full_text) → 判断阈值
  ├─ bypass: split_text_by_token_window(full_text) → TextSegment → Chunk
  └─ normal: detect_chapters → build_chunks（内部再次编码）
Step 3: Persist

新流程：
Step 0: encode_pages_incremental(parsed, threshold) → PageTokenIndex | None
Step 1: Open PDF
Step 2:
  ├─ PageTokenIndex 存在 → bypass（从池切窗口 → Chunk，精确 page_range）
  └─ PageTokenIndex 为 None → 全量编码 → detect_chapters → build_chunks（复用池）
Step 3: Persist
```

### 编码次数对比

| 场景 | 当前方案 | 优化后 |
| --- | --- | --- |
| 直通成功（3 窗口） | 1（count_tokens）+ 3（slice_tokens）= **4 次全量 encode** | **逐页 encode 1 次**，窗口只做 decode |
| 直通失败 → 正常路径（5 章节，2 章超长各 3 窗口） | 1（count_tokens 白做）+ 5（章节计数）+ 6（窗口 slice）= **12 次 encode** | **全量逐页 encode 1 次**，全程 0 次额外 encode |

### 内存开销

使用 `array.array('I')`（unsigned int，4 bytes/token）：

| 文档规模 | token 数 | array.array 内存 | list[int] 内存 |
| --- | --- | --- | --- |
| 普通年报（50 页） | ~50K | ~200 KB | ~1.8 MB |
| 大型年报（300 页） | ~300K | ~1.2 MB | ~10.8 MB |
| 3 倍窗口上限（max=300K） | ~900K | ~3.6 MB | ~32 MB |

### tiktoken + array.array 兼容性

tiktoken 的 `decode()` 类型标注为 `list[int]`，底层 Rust (PyO3) 的 `FromPyObject` 支持任意可迭代对象，`array.array` 运行时可能直接兼容。但为安全起见，**decode 时只转当前窗口的 slice**：

```python
window_ids = all_token_ids[start:end]  # array.array slice
text = encoder.decode(list(window_ids))  # 转 list 再 decode
```

窗口大小为 max_tokens（如 300K），`list()` 转换开销可忽略。存储层面的 8 倍内存节省远大于 decode 时的微量转换成本。

---

## 契约定义

### `core/data/token_indexer.py`

```python
"""Token ID 池化模块。

逐页编码 ParsedDocument，产出共享的 token ID 池 + 页码边界索引。
供 chunk_pipeline 和 chunker 全程复用，避免重复编码。
"""

from __future__ import annotations

import array
from dataclasses import dataclass

from core.data.models import ParsedDocument
from core.data.token_counter import get_encoder

@dataclass(frozen=True)
class PageTokenIndex:
    """逐页编码结果，作为 pipeline 内部共享的 token ID 池。

    Attributes:
        token_ids: 全文档的 token ID 扁平数组（unsigned int, 4 bytes/token）。
        page_boundaries: 每页的 (page_number, token_start_index)，按页码升序。
        total_tokens: token 总数，等于 len(token_ids)。
    """

    token_ids: array.array  # array('I')
    page_boundaries: list[tuple[int, int]]
    total_tokens: int

def encode_pages_incremental(
    parsed: ParsedDocument,
    threshold: int | None = None,
) -> PageTokenIndex | None:
    """逐页编码 ParsedDocument，累积 token IDs 到 array.array。

    逐页调用 encoder.encode()，记录页码边界。
    页间以 "\\n\\n" 分隔（与 ParsedDocument.full_text 保持一致）。

    如果设置了 threshold 且累积 token 数超过该值，提前返回 None。
    如果未设置 threshold，始终编码所有页面。

    BPE 一致性：由于页间有 "\\n\\n" 分隔符，BPE 不会跨越换行合并，
    因此逐页 encode + extend ≈ 全文 encode。建议用测试验证。

    Args:
        parsed: Step 1 产出的 ParsedDocument。
        threshold: 可选，token 总数阈值。超过时提前返回 None。

    Returns:
        PageTokenIndex，或 None（仅在设置 threshold 且超过时）。
    """
    raise NotImplementedError

def find_page_at_token(
    page_boundaries: list[tuple[int, int]],
    token_idx: int,
) -> int:
    """二分查找 token_idx 所在的页码（1-based）。

    Args:
        page_boundaries: encode_pages_incremental 产出的页码边界列表。
        token_idx: token 索引（0-based）。

    Returns:
        该 token 所在的页码（1-based）。
    """
    raise NotImplementedError

def slice_window_from_index(
    index: PageTokenIndex,
    start: int,
    length: int,
) -> tuple[str, int, tuple[int, int]]:
    """从 token ID 池中切取窗口，decode 为文本，并计算页码范围。

    Args:
        index: encode_pages_incremental 产出的 PageTokenIndex。
        start: 窗口起始 token 索引（0-based）。
        length: 窗口 token 数量。

    Returns:
        (text, actual_token_count, (page_start, page_end)) 三元组。
        actual_token_count 可能小于 length（当窗口超出文档末尾时）。
    """
    raise NotImplementedError

def get_chapter_token_count(
    index: PageTokenIndex,
    start_page: int,
    end_page: int,
) -> int:
    """计算指定页码范围内的 token 总数（含页间分隔符）。

    从 page_boundaries 直接计算，无需编码。

    Args:
        index: PageTokenIndex。
        start_page: 起始页码（1-based，含）。
        end_page: 结束页码（1-based，含）。

    Returns:
        该页码范围内的 token 数。
    """
    raise NotImplementedError
```

### `token_counter.py` 变更

将 `_get_encoder` 重命名为 `get_encoder` 并公开导出：

```python
# 变更前
def _get_encoder() -> tiktoken.Encoding:
    ...

# 变更后
def get_encoder() -> tiktoken.Encoding:
    """获取或懒加载 tiktoken 编码器（单例）。"""
    ...
```

同时更新模块内 `count_tokens`、`slice_tokens` 的调用点。

---

## 执行计划

### 前置条件

- Python 3.13 + tiktoken 已安装
- master 分支最新代码
- 现有测试全部通过：`pytest tests/ -v`

### Git 准备

```bash
git checkout master && git pull && git checkout -b refactor/token-id-pooling
```

---

### 阶段 A：基础设施

**步骤 1：`token_counter.py` — 公开 `get_encoder`**

- 操作类型：重构操作
- 重构手法：重命名（Rename）
- 目标文件：`core/data/token_counter.py`
- 描述：将 `_get_encoder` 重命名为 `get_encoder`，去掉下划线前缀使其成为公开 API。更新模块内 `count_tokens` 和 `slice_tokens` 中的调用点。
- 验证：`pytest tests/test_token_counter.py -v`
- Git 提交：`refactor: rename _get_encoder to get_encoder as public API`
- depends_on: none

**步骤 2：新增 `core/data/token_indexer.py` — 契约与 stub**

- 操作类型：新增文件
- 目标文件：`core/data/token_indexer.py`
- 描述：创建新模块，包含上述契约定义中的所有 dataclass 和函数签名（stub 为 `raise NotImplementedError`）。导入 `get_encoder` 来自 `token_counter`。
- 验证：`pyright core/data/token_indexer.py`
- Git 提交：`feat: add token_indexer module contracts`
- depends_on: [步骤 1]

**步骤 3：编写 `token_indexer` 测试**

- 操作类型：新增文件
- 目标文件：`tests/test_token_indexer.py`
- 描述：编写以下测试用例：
    - `test_single_page_document`：单页文档，验证 token_ids 长度 = count_tokens 结果
    - `test_multi_page_boundaries`：多页文档，验证 page_boundaries 记录正确
    - `test_threshold_exceeded_returns_none`：超过阈值返回 None
    - `test_threshold_not_exceeded_returns_index`：未超过阈值返回完整 PageTokenIndex
    - `test_no_threshold_always_completes`：不设阈值，大文档也完成编码
    - `test_bpe_consistency`：逐页 encode + extend vs 全文 encode，token 数一致
    - `test_find_page_at_token`：各种位置的页码查找
    - `test_find_page_at_token_boundary`：恰好在页面边界的 token
    - `test_slice_window_from_index`：切窗口文本 + 页码范围正确
    - `test_slice_window_cross_page`：窗口跨页时页码范围精确
    - `test_get_chapter_token_count`：章节 token 计数 vs 编码验证
    - `test_array_memory_type`：验证 token_ids 是 `array.array` 而非 `list`
- 验证：`pytest tests/test_token_indexer.py -v`（全部 NotImplementedError FAILED）
- Git 提交：`test: add tests for token_indexer module`
- depends_on: [步骤 2]

**步骤 4：实现 `token_indexer` 所有函数**

- 操作类型：实现
- 目标文件：`core/data/token_indexer.py`
- 描述：
    - `encode_pages_incremental`：逐页 `encoder.encode(page.markdown_text)`，extend 到 `array.array('I')`，页间加 `encoder.encode("\n\n")`（最后一页不加），检查 threshold
    - `find_page_at_token`：在 page_boundaries 上做二分查找（`bisect_right`）
    - `slice_window_from_index`：切片 `token_ids[start:end]`，`list()` 转换后 `encoder.decode()`，调用 `find_page_at_token` 计算页码范围
    - `get_chapter_token_count`：找到起止页的 token 边界，相减
- 验证：`pytest tests/test_token_indexer.py -v`（全部 PASSED）
- Git 提交：`feat: implement token_indexer with array.array storage`
- depends_on: [步骤 3]

---

### 阶段 B：直通路径重构

**步骤 5：`chunk_pipeline.py` — 替换 Step 2 直通路径**

- 操作类型：重构操作
- 重构手法：提取函数 + 替换算法
- 目标文件：`core/data/chunk_pipeline.py`
- 描述：
    - 移除 `from core.data.chunker import split_text_by_token_window`
    - 新增 `from core.data.token_indexer import encode_pages_incremental, slice_window_from_index, PageTokenIndex`
    - 将 Step 2 替换为：调用 `encode_pages_incremental(parsed, threshold=BYPASS_THRESHOLD_FACTOR * max_tokens)`
    - 如果返回 PageTokenIndex：用 `slice_window_from_index` 循环切窗口，直接构建 Chunk（带精确 page_range），组装 ChunkList
    - 删除 `_build_bypass_chunk_list` 函数
    - 如果返回 None：进入正常路径
- 验证：`pytest tests/test_chunk_pipeline.py -v`
- Git 提交：`refactor: replace bypass path with token ID pool, fix page_range accuracy`
- depends_on: [步骤 4]

---

### 阶段 C：正常路径优化

**步骤 6：`chunker.py` — `ChunkBuilder.create_chunk` 接受预计算 token_count**

- 操作类型：重构操作
- 重构手法：引入参数（Introduce Parameter）
- 目标文件：`core/data/chunker.py`
- 描述：为 `ChunkBuilder.create_chunk` 添加可选参数 `token_count: int | None = None`。如果传入则跳过内部 `count_tokens(text)` 调用，否则保持现有行为。向后兼容，现有调用方无需修改。
- 验证：`pytest tests/test_chunker.py -v`
- Git 提交：`refactor: add optional token_count to ChunkBuilder.create_chunk`
- depends_on: none（可与阶段 A/B 并发）

**步骤 7：`chunk_pipeline.py` — 正常路径引入全量编码**

- 操作类型：重构操作
- 目标文件：`core/data/chunk_pipeline.py`
- 描述：在正常路径（bypass 返回 None 后），调用 `encode_pages_incremental(parsed)`（不设 threshold）获取完整 PageTokenIndex，传递给 `build_chunks`。
- 验证：`pytest tests/test_chunk_pipeline.py -v`
- Git 提交：与步骤 8 合并提交
- depends_on: [步骤 5]

**步骤 8：`chunker.py` — `build_chunks` 接受 PageTokenIndex**

- 操作类型：重构操作
- 重构手法：引入参数对象（Introduce Parameter Object）
- 目标文件：`core/data/chunker.py`
- 描述：
    - `build_chunks` 签名新增 `token_index: PageTokenIndex | None = None`
    - 如果传入 token_index：章节 token 计数改用 `get_chapter_token_count(index, start_page, end_page)` 替代 `count_tokens(chapter_text)`；传递预计算 token_count 给 `ChunkBuilder.create_chunk`
    - 如果未传入：保持现有行为（向后兼容）
    - 将 token_index 透传给 `_split_by_token_window`
- 验证：`pytest tests/test_chunker.py -v`
- Git 提交：`refactor: use PageTokenIndex in build_chunks for zero-cost token counting`
- depends_on: [步骤 6, 步骤 7]

**步骤 9：`chunker.py` — `_split_by_token_window` 使用 token ID 池**

- 操作类型：重构操作
- 重构手法：替换算法
- 目标文件：`core/data/chunker.py`
- 描述：
    - `_split_by_token_window` 签名新增 `token_index: PageTokenIndex | None = None`
    - 如果传入 token_index：根据 chapter 的 page_range 计算该章节在 token_ids 中的起止索引，用 `slice_window_from_index` 切窗口（自带精确 page_range），不再调用 `split_text_by_token_window`
    - 如果未传入：保持现有行为（向后兼容）
- 验证：`pytest tests/test_chunker.py -v`，特别关注 overlap 相关测试
- Git 提交：`refactor: use token ID pool in _split_by_token_window`
- depends_on: [步骤 8]

---

### 阶段 D：清理

**步骤 10：移除 `split_text_by_token_window`**

- 操作类型：清理
- 目标文件：`core/data/chunker.py`
- 描述：删除 `split_text_by_token_window` 函数（所有调用方已迁移）。确认无外部引用：`grep -rn "split_text_by_token_window" core/ tests/`。更新相关 import。
- 验证：`pytest tests/ -v`
- Git 提交：`refactor: remove split_text_by_token_window`
- depends_on: [步骤 9]

**步骤 11：移除 `TextSegment`**

- 操作类型：清理
- 目标文件：`core/data/models.py`、`core/data/chunker.py`、`core/data/chunk_pipeline.py`
- 描述：
    - 从 `models.py` 中删除 `TextSegment` dataclass
    - 从 `chunker.py` 和 `chunk_pipeline.py` 的 import 中移除 `TextSegment`
    - 确认无外部引用：`grep -rn "TextSegment" core/ tests/`
    - 删除 `tests/test_chunker.py` 中 `TestSplitTextByTokenWindow` 测试类
- 验证：`pytest tests/ -v && pyright core/`
- Git 提交：`refactor: remove TextSegment dataclass and related tests`
- depends_on: [步骤 10]

**步骤 12：整体验证**

- 操作类型：校验
- 描述：运行全量测试、类型检查，确认无残留旧函数引用

```bash
pytest tests/ -v
pyright core/data/
grep -rn "split_text_by_token_window\|TextSegment\|_get_encoder\|_build_bypass_chunk_list" core/ tests/
```

- depends_on: [步骤 11]
- Git 提交：如有未提交变更，`refactor: final cleanup for token-id-pooling`

---

### 并发依赖图

```
阶段 A（串行）：
步骤 1 → 步骤 2 → 步骤 3 → 步骤 4

阶段 B（串行，依赖 A）：
步骤 5 → depends_on: [步骤 4]

阶段 C:
  步骤 6 → depends_on: none（可与 A/B 并发）
  步骤 7 → depends_on: [步骤 5]
  步骤 8 → depends_on: [步骤 6, 步骤 7]
  步骤 9 → depends_on: [步骤 8]

阶段 D（串行，依赖 C）：
步骤 10 → 步骤 11 → 步骤 12
```

---

## 影响范围

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `core/data/token_counter.py` | 修改 | `_get_encoder` → `get_encoder`（公开） |
| `core/data/token_indexer.py` | 新增 | PageTokenIndex + encode_pages_incremental + 辅助函数 |
| `core/data/chunk_pipeline.py` | 修改 | Step 2 重构 + 正常路径引入 PageTokenIndex |
| `core/data/chunker.py` | 修改 | build_chunks / _split_by_token_window 接受 token_index；移除 split_text_by_token_window |
| `core/data/models.py` | 修改 | 移除 TextSegment |
| `tests/test_token_indexer.py` | 新增 | token_indexer 模块完整测试 |
| `tests/test_token_counter.py` | 修改 | 更新 get_encoder 引用（如有） |
| `tests/test_chunker.py` | 修改 | 移除 TestSplitTextByTokenWindow；更新 import |
| `tests/test_chunk_pipeline.py` | 修改 | 更新直通路径测试；验证 page_range 精确性 |

---

## 验证清单

```bash
# 全量测试
pytest tests/ -v

# 类型检查
pyright core/data/

# BPE 一致性验证
pytest tests/test_token_indexer.py::test_bpe_consistency -v

# page_range 精确性验证
pytest tests/test_chunk_pipeline.py -k "page_range" -v

# 确认无残留
grep -rn "split_text_by_token_window\|TextSegment\|_get_encoder\|_build_bypass_chunk_list" core/ tests/
```

---

## 技术决策说明

| 决策 | 理由 | Trade-off |
| --- | --- | --- |
| 使用 `array.array('I')` 而非 `list[int]` | 内存降低 8 倍（4 bytes vs ~36 bytes/token），900K tokens 仅 3.6MB | decode 时需 `list()` 转换当前窗口，开销可忽略 |
| 直通路径提前退出（threshold） | 大文档无需编码全部页面即可判断是否走直通 | 如果走正常路径，需再次全量编码；重叠部分最多 3x max_tokens |
| 正常路径也全量编码 | 避免 build_chunks / _split_by_token_window 中的 N 次重复编码 | 多一次全量编码，但消除了所有重复编码，净收益为正 |
| 直接产出 Chunk，移除 TextSegment | TextSegment 作为中间层已无存在必要，所有路径都从 token ID 池直接构建 Chunk | 无，纯简化 |
| 新建 token_[indexer.py](http://indexer.py) 而非扩展 token_[counter.py](http://counter.py) | token_counter 是纯工具模块（无领域依赖），token_indexer 依赖 ParsedDocument（领域模型），职责不同 | 多一个文件，但依赖关系清晰 |
| 页间分隔符手动编码 | 需与 ParsedDocument.full_text 的 "\n\n" 拼接行为保持一致 | 需测试验证 BPE 一致性；如果 full_text 分隔符变更需同步更新 |