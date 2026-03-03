# tdd-green：实现参考与实现步骤（Step 2）

## 目标概述

将 Step 1 输出的 `ParsedDocument`（按页分块的 Markdown + 元信息）进行**章节感知的逻辑分块**，产出适配 DeepSeek 上下文窗口的 `ChunkList`，供 Step 3 摘要 Agent 消费。同时将分块结果持久化到本地存储（SQLite 元信息 + 文件系统 Markdown 分段）。

---

## 前置条件

- Python 3.13+ 虚拟环境已就绪
- Step 1 的 `ParsedDocument`、`ParsedPage` 数据结构已可用（`core/data/models.py`）
- 已安装 `pymupdf`（用于书签提取）、`pymupdf4llm`（page_chunks 模式提供 `toc_items`）
- 需新增依赖：`tiktoken`（`pip install tiktoken`，用于精确 token 计数）
- **阶段 A（tdd-red）已完成**：契约定义、测试用例已就位，所有测试处于 Red 状态

---

## ▶ 阶段 B：`/tdd-green` 执行以下步骤

### 6. 核心实现参考

#### 6.1 PyMuPDF — TOC / 书签提取

**来源**：[PyMuPDF 官方文档 Document 类](https://pymupdf.readthedocs.io/en/latest/document.html) (v1.27.1)

```python
import pymupdf

doc = pymupdf.open("input.pdf")

# 获取目录/书签列表
# 返回 [[level, title, page_number, ...], ...]
# level: 层级（1 为顶级）
# page_number: 1-based 页码
toc = doc.get_toc()  # type: list[list]

# 示例返回值：
# [[1, "第一章 概述", 1], [2, "1.1 背景", 2], [1, "第二章 分析", 5]]

# 设置 TOC（用于测试）
doc.set_toc(toc)

# 检查文档是否加密
if doc.is_encrypted:
    # 处理加密
    pass

# 页面数
total = doc.page_count  # int

doc.close()
```

**注意事项**：

- `get_toc()` 返回空列表 `[]` 表示 PDF 无书签
- `page_number` 是 1-based
- 部分财报 PDF 的书签可能指向错误页码，需验证

#### 6.2 PyMuPDF4LLM — page_chunks 模式

**来源**：[PyMuPDF4LLM API 文档](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html) (≥ 0.0.23)

```python
import pymupdf4llm

# page_chunks=True 返回每页的字典列表
chunks = pymupdf4llm.to_markdown(doc, page_chunks=True)

# 每个 chunk 的 schema：
# {
#     "metadata": {...},
#     "toc_items": [[level, title, page_number], ...],  # 指向该页的目录条目
#     "tables": [...],
#     "images": [...],
#     "graphics": [...],
#     "text": "Markdown 文本"
# }

# toc_items 可用于交叉验证书签与实际页面内容的对应关系
```

#### 6.3 tiktoken — Token 计数

**来源**：[tiktoken PyPI](https://pypi.org/project/tiktoken/) + [OpenAI Cookbook](https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken/)

```python
import tiktoken

# 加载编码器（首次需联网下载，后续离线可用）
enc = tiktoken.get_encoding("cl100k_base")

# 计算 token 数
tokens = enc.encode("这是一段测试文本。")
token_count = len(tokens)  # int

# 解码回文本
text = enc.decode(tokens)  # str

# 截断到指定 token 数
truncated_tokens = tokens[:max_tokens]
truncated_text = enc.decode(truncated_tokens)
```

**注意事项**：

- `cl100k_base` 兼容 GPT-4、DeepSeek 等主流模型
- DeepSeek 使用自有 tokenizer，但 cl100k_base 的计数足够作为安全上限估算
- 中文文本平均约 1.5~2 tokens/字
- 编码器实例应复用（单例），避免重复加载

#### 6.4 aiosqlite — 异步 SQLite 操作

**来源**：项目现有代码 `core/db/__init__.py`

```python
import aiosqlite

# 连接数据库
async with aiosqlite.connect("path/to/db.sqlite") as db:
    # 创建表
    await db.execute("""
        CREATE TABLE IF NOT EXISTS chunk_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            report_date TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chapter_title TEXT,
            chapter_path TEXT,  -- JSON 序列化
            page_start INTEGER,
            page_end INTEGER,
            token_count INTEGER,
            chunk_type TEXT,
            needs_prior_summary INTEGER,
            md_file_path TEXT,
            UNIQUE(stock_code, report_date, chunk_index)
        )
    """)
    await db.commit()

    # 插入数据
    await db.executemany(
        "INSERT INTO chunk_meta (...) VALUES (...)",
        data_list,
    )
    await db.commit()
```

#### 6.5 正则表达式 — 目录页、标题和中文编号检测

```python
import re

# 检测目录页关键词
toc_pattern = re.compile(r"目\s*录|CONTENTS|Table\s+of\s+Contents", re.IGNORECASE)

# 提取目录项（章节名 + 页码）
# 匹配模式如："第一节 重要提示 ......... 5"
toc_entry_pattern = re.compile(
    r"^(.+?)\s*[.…·\-_]{3,}\s*(\d+)\s*$",
    re.MULTILINE,
)

# 检测 Markdown 标题
heading_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# 中文财报常见编号模式（用于 HeadingStrategy 和 _split_by_subheadings）
# 匹配：第一节、第2章、一、、（一）、1、、1.1 等
cn_section_pattern = re.compile(
    r"^\*{0,2}(?:"
    r"第[一二三四五六七八九十\d]+(?:节|章|部分)"
    r"|[一二三四五六七八九十]+[、.]"
    r"|[（(][一二三四五六七八九十\d]+[)）]"
    r"|\d+[、.](?!\d)"
    r"|\d+\.\d+"
    r")\s*.+$",
    re.MULTILINE,
)

# 编号层级推断规则（用于分配 ChapterBoundary.level）：
# level 1: 「第X节/章」「第X部分」
# level 2: 「一、」「二、」 或 「1、」「2、」
# level 3: 「（一）」「(1)」 或 「1.1」「2.3」
# level 4: 「1.1.1」 或更深层
```

### 7. 实现步骤

#### 步骤 7.1：实现 token_counter 模块

- **操作类型**：修改文件
- **目标文件**：`core/data/token_counter.py`
- **描述**：实现 `_get_encoder`（单例懒加载 tiktoken 编码器）、`count_tokens`（调用编码器计算 token 数）、`truncate_to_tokens`（编码→截断→解码）
- **参考**：6.3 tiktoken API
- **验证**：`pytest tests/test_token_counter.py -v`
- **Git**：暂不提交
- **depends_on**: none

#### 步骤 7.2：实现 BookmarkStrategy

- **操作类型**：修改文件
- **目标文件**：`core/data/chapter_detector.py`
- **描述**：实现 `BookmarkStrategy.detect`。逻辑要点：
    1. 调用 `doc.get_toc()` 获取书签列表
    2. **保留所有层级**的书签（不再只取 level=1），将 level 直接映射到 `ChapterBoundary.level`
    3. 对每个书签，检查对应页面的 `parsed.pages[page-1].text` 中是否包含匹配的标题文本（模糊匹配，去除空格后比较）
    4. 验证通过的书签转换为 `ChapterBoundary`，计算每个章节的 end_page（下一个**同级或更高级**书签的 start_page - 1）
    5. 有效书签不足 2 个时返回 None
    6. **chunker 侧利用 level 信息**：`build_chunks` 优先按 level=1 边界切分，超长章节内部可利用 level≥2 的子章节边界做二次拆分（替代纯正则子标题检测）
- **参考**：6.1 PyMuPDF get_toc API
- **验证**：`pytest tests/test_chapter_detector.py::TestBookmarkStrategy -v`
- **Git**：暂不提交
- **depends_on**: none
- **可并发**：与步骤 7.1 并发

#### 步骤 7.3：实现 TocPageStrategy

- **操作类型**：修改文件
- **目标文件**：`core/data/chapter_detector.py`
- **描述**：实现 `TocPageStrategy.detect`。逻辑要点：
    1. 遍历前 `MAX_SEARCH_PAGES` 页，用类属性 `TOC_PATTERN` 正则检测是否为目录页（支持「目录」「目 录」及任意空格变体）
    2. 在目录页中用 `toc_entry_pattern` 提取章节名和印刷页码
    3. 计算 PDF 页码偏移：找到第一个可验证的目录项，用其印刷页码与实际出现位置的差值作为偏移量
    4. 应用偏移量，将印刷页码转换为 PDF 页码
    5. 转换为 `ChapterBoundary` 列表
    6. 匹配项不足 2 个时返回 None
- **参考**：6.5 正则表达式模式
- **验证**：`pytest tests/test_chapter_detector.py::TestDetectChapters -v`（部分）
- **Git**：暂不提交
- **depends_on**: 步骤 7.2

#### 步骤 7.4：实现 HeadingStrategy

- **操作类型**：修改文件
- **目标文件**：`core/data/chapter_detector.py`
- **描述**：实现 `HeadingStrategy.detect`。逻辑要点：
    1. 遍历所有 `parsed.pages`，**双通道检测**：
        - 通道 A：用 `heading_pattern` 提取 Markdown 标题（`#`、`##`、`###`）
        - 通道 B：用 `CN_SECTION_PATTERN` 提取中文编号标题（第X节、一、、1.1 等）
    2. 合并两个通道的匹配结果，按页码排序
    3. 对中文编号匹配，根据 6.5 层级推断规则分配 level（第X节→1，一、→2，1.1→3 等）
    4. **保留所有层级标题**（与 BookmarkStrategy 行为对齐），根据 6.5 层级推断规则分配 level（Markdown: `#`→1, `##`→2, `###`→3；中文编号: 第X节→1, 一、→2, （一）/1.1→3）
    5. 利用 `toc_items` 做交叉验证（如果可用）
    6. 有效标题不足 2 个时返回 None
- **参考**：6.5 正则表达式模式（`heading_pattern` + `cn_section_pattern`）
- **验证**：`pytest tests/test_chapter_detector.py::TestHeadingStrategy -v`
- **Git**：暂不提交
- **depends_on**: none
- **可并发**：与步骤 7.3 并发

#### 步骤 7.5：实现 FallbackStrategy 和 detect_chapters

- **操作类型**：修改文件
- **目标文件**：`core/data/chapter_detector.py`
- **描述**：
    1. `FallbackStrategy.detect`：返回覆盖全文的单一 ChapterBoundary（`start_page=1, end_page=parsed.total_pages`），不做 token 计数或窗口切分
    2. `detect_chapters`：按优先级实例化并执行策略链 `[BookmarkStrategy, TocPageStrategy, HeadingStrategy, FallbackStrategy]`，首个非 None 结果生效
- **参考**：无额外依赖（FallbackStrategy 不再需要 tiktoken）
- **验证**：`pytest tests/test_chapter_detector.py -v`（全部通过）
- **Git**：提交 → `feat: implement chapter detection with multi-level fallback`
- **depends_on**: 步骤 7.2, 7.3, 7.4

#### 步骤 7.6：实现 chunker 模块

- **操作类型**：修改文件
- **目标文件**：`core/data/chunker.py`
- **描述**：实现 `build_chunks`、`_merge_same_page_boundaries`、`_extract_chapter_text`、`_split_by_subheadings`、`_split_by_token_window`。逻辑要点：
    1. `build_chunks` 入口优先级链：
        - **Step 0 整体直通**：拼接全文，若 `count_tokens(full_text) ≤ max_tokens`，直接返回单个 `COMPLETE_CHAPTER` Chunk，跳过后续所有逻辑
        - **Step 1 同页合并（level=1）**：调用 `_merge_same_page_boundaries(level1_chapters)` 对 level=1 章节做预处理
        - **Step 2+ 正常流程**：遍历合并后的章节列表，短章节 → `COMPLETE_CHAPTER`，长章节 → 进入 Step 3
        - **Step 3 超长章节二次拆分**：
            - a. 从完整 `chapters` 列表中过滤该 level=1 章节 page_range 内的 level≥2 子边界
            - b. 对子边界调用 `_merge_same_page_boundaries()` 做同页合并
            - c. 将合并后的子边界通过 `sub_boundaries` 参数传给 `_split_by_subheadings`
            - d. 无预检测边界时，`_split_by_subheadings` 退回正则子标题检测
            - e. 仍超长的子节继续调 `_split_by_token_window`
    2. `_merge_same_page_boundaries`（通用版本）：遍历边界列表，若相邻边界 `start_page` 和 `end_page` 完全相同，合并为一个虚拟章节（title 用 " / " 拼接，level 取最小，page_range 取并集，source 保留第一个）
    3. `_extract_chapter_text`：按 `page_range` 拼接 `parsed.pages` 的文本
    4. `_split_by_subheadings`：优先使用 `sub_boundaries` 预检测边界按页码范围切分；无预检测边界时退回**双通道正则检测**（Markdown `##`/`###` + 中文编号），每段检查 token 数，超长段继续调 `_split_by_token_window`
    5. `_split_by_token_window`：按段落边界 `\n\n` 累积 token，达到上限时切分，保留 overlap
    6. 设置 `needs_prior_summary`：每个顶级章节的第一个 chunk 从第 2 章开始标记为 True
    7. **填充 `contained_chapters`**：在构造每个 Chunk 时填充 `contained_chapters: list[ChunkMeta]`
        - 单章节 COMPLETE_CHAPTER：`[ChunkMeta(title, level, page_range)]`（自身）
        - 同页合并 Chunk：记录合并前所有原始章节的 ChunkMeta
        - 整体直通 Chunk：所有 level=1 章节转为 ChunkMeta
        - 子块拆分 Chunk（SUB_SECTION / TOKEN_WINDOW）：继承父章节的 `[ChunkMeta]`
- **参考**：6.3 tiktoken 计数，6.5 正则标题提取
- **验证**：`pytest tests/test_chunker.py -v`（含 `TestLevel2SamePageMerge` 新增用例）
- **Git**：提交 → `feat: implement chunking engine with sub-section splitting`
- **depends_on**: 步骤 7.5

#### 步骤 7.7：实现 chunk_storage 模块

- **操作类型**：修改文件
- **目标文件**：`core/data/chunk_storage.py`
- **描述**：实现 `init_chunk_tables`、`save_chunks`、`load_chunks`。逻辑要点：
    1. `init_chunk_tables`：创建 `chunk_meta` 表（含 stock_code, report_date, chunk_index 等列）
    2. `save_chunks`：写入 SQLite 元信息 + 创建目录结构 + 写入 `.md` 文件（UTF-8 编码）
    3. `load_chunks`：从 SQLite 查询元信息 + 从文件系统读取 `.md` 文件 + 还原为 ChunkList
- **参考**：6.4 aiosqlite 操作模式
- **验证**：`pytest tests/test_chunk_storage.py -v`
- **Git**：提交 → `feat: implement chunk storage with SQLite and filesystem`
- **depends_on**: none
- **可并发**：与步骤 7.6 并发

#### 步骤 7.8：实现 logical_chunker 主入口

- **操作类型**：修改文件
- **目标文件**：`core/data/logical_chunker.py`
- **描述**：实现 `chunk_document`。逻辑要点：
    1. 调用 `pymupdf.open(stream=content, filetype="pdf")` 打开 PDF
    2. 调用 `detect_chapters` 识别章节
    3. 调用 `build_chunks` 生成 ChunkList
    4. 若 `persist=True`，调用 `save_chunks` 持久化
    5. 用 `logfire.info` 记录统计信息（章节数、块数、总 token 数）
    6. `finally` 中确保 `doc.close()`
- **参考**：6.1 PyMuPDF Document 管理
- **验证**：手动集成测试
- **Git**：提交 → `feat: implement logical chunker entry point`
- **depends_on**: 步骤 7.6, 7.7

### 8. 验证清单

```bash
# 激活虚拟环境
./venv/Scripts/activate

# 全量测试
pytest tests/test_token_counter.py tests/test_chapter_detector.py tests/test_chunker.py tests/test_chunk_storage.py -v

# 现有测试无回归
pytest tests/ -v

# 类型检查
pyright core/data/token_counter.py core/data/chapter_detector.py core/data/chunker.py core/data/chunk_storage.py core/data/logical_chunker.py
```

### 9. 测试补充

实现完成后，评估以下额外测试场景：

- [ ]  真实财报 PDF 的端到端测试（`@pytest.mark.real_network`）
- [ ]  目录页偏移的边界情况（封面页、前言页导致的偏移）
- [ ]  中英文混合文本的 token 计数精确性
- [ ]  并发持久化的线程安全性
- [ ]  超大文档（>200 页）的性能测试（`@pytest.mark.slow`）

### 10. 技术决策说明

#### 为什么用 tiktoken 而不是 DeepSeek 原生 tokenizer？

**Trade-off**：

- tiktoken（cl100k_base）的 token 计数与 DeepSeek tokenizer 不完全一致
- 但 cl100k_base 对中文的计数偏高，可作为安全上限
- DeepSeek 无官方 Python tokenizer 包，自行实现不稳定
- 后续可通过调整 `DEFAULT_MAX_TOKENS` 的值来校准

#### 为什么章节间不做 overlap？

**设计选择**：采用「前章摘要注入」而非「文本 overlap」

- 章节间是逻辑独立的，不像段落存在切断风险
- 前章摘要提供的上下文更精练（比 overlap 原文更有效）
- 只在章节内子块拆分时使用 overlap（子块间可能切断段落）

#### 为什么持久化用 SQLite + 文件系统而非纯 SQLite？

**理由**：

- Markdown 文本可能很长（数万字符），放入 SQLite TEXT 列会影响查询性能
- 文件系统存储便于直接浏览和调试
- SQLite 只存元信息索引，查询快速
- 与项目现有的 `core/db/` 模式一致

---

## 依赖关系图与并发策略

```jsx
阶段 1（串行）：契约定义 → 测试用例 → git commit

阶段 2（并发）：
    ├─ Sub-agent A：步骤 7.1（token_counter）→ 运行测试
    ├─ Sub-agent B：步骤 7.2（BookmarkStrategy）→ 运行测试
    └─ Sub-agent C：步骤 7.4（HeadingStrategy）→ 运行测试

阶段 3（串行）：
    步骤 7.3（TocPageStrategy，依赖 7.2）
    → 步骤 7.5（FallbackStrategy + detect_chapters，依赖 7.1~7.4）
    → git commit

阶段 4（并发）：
    ├─ Sub-agent D：步骤 7.6（chunker，依赖 7.5）→ 运行测试 → commit
    └─ Sub-agent E：步骤 7.7（chunk_storage）→ 运行测试 → commit

阶段 5（串行）：
    步骤 7.8（logical_chunker，依赖 7.6 + 7.7）→ commit
    → 全量验证 → 最终 commit
```

---

## 待验证事项

> 以下需要用户确认或在实现过程中验证：
> 
- [ ]  **DeepSeek 有效摘要窗口**：`DEFAULT_MAX_TOKENS = 8000` 是否合适？需要实际测试不同长度下的摘要质量
- [ ]  **tiktoken 与 DeepSeek 的 token 差异**：cl100k_base 计数是否可作为安全上限？
- [ ]  **目录页格式**：真实财报的目录页是否有足够规律可解析？不同券商/交易所格式差异如何？
- [ ]  **PDF 书签可靠性**：PyMuPDF `get_toc()` 在各类财报上的实际返回数据需要采样验证
- [ ]  **最佳 overlap 大小**：`OVERLAP_TOKENS = 200` 是否合适？
- [ ]  **是否需要安装 `pymupdf-layout`**：Layout 包可提升表格和页眉页脚检测，但引入 ML 模型，需评估 i3 Mac Mini 性能