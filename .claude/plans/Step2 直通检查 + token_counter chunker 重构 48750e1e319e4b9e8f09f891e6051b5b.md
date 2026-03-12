# Step2 直通检查 + token_counter/chunker 重构

任务时间段: 2026年3月11日 16:45 (GMT+8)
任务进度: 0/1 (0%)
最后编辑时间: 2026年3月11日 17:14
父任务: 计划本地解析PDF以及使用三方模型API来完成总结 (https://www.notion.so/PDF-API-3126e81bcc0280038816cf17821e797e?pvs=21)
状态: 已计划
ID: 49
同级任务已完成: No

## 目标概述

在 chunk_pipeline 的 Step 2 添加直通检查（bypass），对 3 倍 max_tokens 以内的文档直接按最大窗口拆分，跳过章节识别流程。同时重构 `token_counter.py` 和 `chunker.py` 以支撑该功能。

---

## 背景分析

### 问题 1：`token_counter.py` 缺少通用切片函数

- 现有 `truncate_to_tokens`（取首部）和 `truncate_tail_tokens`（取尾部）无法实现「从第 X 个 token 截取 Y 个 token」的滑动窗口语义
- 在 `_split_by_token_window` 中组合使用时，会导致 **overlap 区间与 segment 截断之间的内容丢失**
- 直通检查场景需要按 token 偏移量循环截取窗口，现有函数无法胜任

### 问题 2：`chunker.py` 函数拆分粒度不足

- `_split_by_token_window` 耦合了 Chunk 构建逻辑（需要 `chapter_path`、`page_range` 等参数），无法从 `chunk_pipeline.py` 直接调用
- 所有拆分函数均为私有（下划线前缀），外部模块无法复用
- 缺少一个纯文本级别的「按 token 窗口拆分」公开函数

### 问题 3：`chunk_pipeline.py` 直通检查未实现

- 当前 Step 2 的直通分支内只有 `pass`，实际仍会走完整的章节识别流程
- 直通优化未生效

---

## 改造方案

### 1. `token_counter.py` — 新增 `slice_tokens`

- 签名：`slice_tokens(text: str, start: int, length: int) -> str`
- 从第 `start` 个 token 开始，截取 `length` 个 token 的文本
- 可完全替代 `truncate_to_tokens` 和 `truncate_tail_tokens`：
    - `truncate_to_tokens(text, n)` → `slice_tokens(text, 0, n)`
    - `truncate_tail_tokens(text, n)` → `slice_tokens(text, total - n, n)`
- 创建 `slice_tokens` 后，**直接移除** `truncate_to_tokens` 和 `truncate_tail_tokens`，同步更新所有调用点

### 2. `chunker.py` — 提取公开的文本拆分函数

- 新增公开函数：`split_text_by_token_window(text, max_tokens, overlap_tokens) -> list[TextSegment]`
- 只负责纯文本的 token 窗口拆分，不涉及 Chunk 构建
- 内部使用 `slice_tokens` 实现无损滑动窗口
- 原有 `_split_by_token_window` 改为调用此函数后再包装为 Chunk

### 3. `chunk_pipeline.py` — 实现直通路径

- Step 2 直通条件：`count_tokens(full_text) < BYPASS_THRESHOLD_FACTOR * max_tokens`（`BYPASS_THRESHOLD_FACTOR = 3`）
- 直通路径：调用 `split_text_by_token_window` 按最大窗口拆分 → 包装为 `ChunkList` → 执行持久化（与正常路径一致）→ 跳过章节识别
- 章节识别交给 LLM 模型在摘要阶段处理

---

## 执行计划（TDD）

### 1. 前置条件

- Python 3.13 + tiktoken 已安装
- master 分支最新代码
- 现有测试全部通过：`pytest tests/ -v`

### 2. Git 准备

```bash
git checkout master && git pull && git checkout -b feat/step2-bypass-and-token-refactor
```

---

### ▶ 阶段 A：`/tdd-red` 契约与测试

### 3. 契约定义

**3.1 `core/data/token_counter.py` — 替换为 `slice_tokens`**

```python
"""Token 计数工具模块。

封装 tiktoken 的 token 计数逻辑，提供简洁接口。
使用 cl100k_base 编码（兼容大多数主流 LLM）。
"""

from __future__ import annotations

import tiktoken

# 使用 cl100k_base 编码，兼容 GPT-4 / DeepSeek 等主流模型
_ENCODING_NAME: str = "cl100k_base"
_encoder: tiktoken.Encoding | None = None

def _get_encoder() -> tiktoken.Encoding:
    """获取或懒加载 tiktoken 编码器（单例）。

    Returns:
        tiktoken.Encoding 实例。
    """
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding(_ENCODING_NAME)
    return _encoder

def count_tokens(text: str) -> int:
    """计算文本的 token 数。

    Args:
        text: 待计数的文本。

    Returns:
        token 数量。
    """
    if not text:
        return 0
    encoder = _get_encoder()
    tokens = encoder.encode(text)
    return len(tokens)

def slice_tokens(text: str, start: int, length: int) -> str:
    """从文本的第 start 个 token 开始，截取 length 个 token 对应的文本。

    在 token 边界处截断，不会切断 UTF-8 字符。
    支持滑动窗口、首部截取、尾部截取等所有切片场景。

    等价关系：
    - 取首部 n 个 token: slice_tokens(text, 0, n)
    - 取尾部 n 个 token: slice_tokens(text, count_tokens(text) - n, n)

    边界行为：
    - start < 0: 自动修正为 0
    - start >= total_tokens: 返回 ""
    - start + length > total_tokens: 截取到文本末尾（不报错）
    - length <= 0: 返回 ""
    - text 为空: 返回 ""

    Args:
        text: 待截取的文本。
        start: 起始 token 索引（0-based）。
        length: 截取的 token 数量。

    Returns:
        截取后的文本。
    """
    raise NotImplementedError
```

**3.2 `core/data/models.py` — 新增 `TextSegment`**

在 `ChunkList` 之后、`PageChunk` 之前新增：

```python
@dataclass(frozen=True)
class TextSegment:
    """纯文本分段结果。

    不含 Chunk 构建所需的章节路径、页码范围等上下文，
    仅用于文本级别的 token 窗口拆分。

    Attributes:
        text: 分段文本内容。
        token_count: 该段的 token 数。
        start_token: 在原始文本中的起始 token 索引（0-based）。
        is_last: 是否为最后一个分段。
    """

    text: str
    token_count: int
    start_token: int
    is_last: bool = False
```

**3.3 `core/data/chunker.py` — 新增公开函数 `split_text_by_token_window`**

在模块顶部 import 区新增 `TextSegment` 导入，并新增公开函数签名：

```python
from core.data.models import (
    ChapterBoundary,
    Chunk,
    ChunkList,
    ChunkMeta,
    ChunkType,
    MergedChapter,
    ParsedDocument,
    TextSegment,  # 新增
)
from core.data.token_counter import (
    count_tokens,
    slice_tokens,  # 替代旧函数
)

def split_text_by_token_window(
    text: str,
    max_tokens: int,
    overlap_tokens: int = 0,
) -> list[TextSegment]:
    """将文本按 token 窗口拆分为多个 TextSegment，保证无内容丢失。

    使用 slice_tokens 实现精确的滑动窗口，每个窗口包含 max_tokens 个 token，
    相邻窗口之间有 overlap_tokens 个 token 的重叠。

    算法：
    1. 计算总 token 数
    2. 若总量 <= max_tokens，直接返回单个 TextSegment
    3. 否则，从 start=0 开始，步长为 max_tokens - overlap_tokens，
       循环调用 slice_tokens(text, start, max_tokens) 产出 TextSegment
    4. 确保最后一个 TextSegment 覆盖到文本末尾

    降级行为：
    - text 为空: 返回空列表
    - max_tokens <= 0: 返回空列表
    - overlap_tokens >= max_tokens: 自动修正 overlap_tokens = 0（避免无限循环）
    - overlap_tokens < 0: 自动修正为 0

    Args:
        text: 待拆分的文本。
        max_tokens: 每个窗口的最大 token 数。
        overlap_tokens: 相邻窗口的重叠 token 数。

    Returns:
        TextSegment 列表，按文本顺序排列。
    """
    raise NotImplementedError
```

**3.4 `core/data/chunk_pipeline.py` — 直通路径签名**

在 `chunk_document` 函数内 Step 2 处新增直通逻辑（伪实现）：

```python
# 新增 import
from core.data.chunker import build_chunks, split_text_by_token_window
from core.data.models import Chunk, ChunkList, ChunkType, ParsedDocument, TextSegment

# 直通阈值倍数
BYPASS_THRESHOLD_FACTOR: int = 3
# Step 2 内部：
def _build_bypass_chunk_list(
    parsed: ParsedDocument,
    segments: list[TextSegment],
    *,
    overlap_tokens: int,
) -> ChunkList:
    """将 TextSegment 列表包装为 ChunkList（直通路径专用）。

    每个 TextSegment 包装为一个 TOKEN_WINDOW 类型的 Chunk，
    chapter_path 为空（交给 LLM 在摘要阶段识别章节），
    page_range 覆盖整个文档。

    Args:
        parsed: 原始 ParsedDocument。
        segments: split_text_by_token_window 产出的分段列表。
        overlap_tokens: overlap token 数（用于日志）。

    Returns:
        ChunkList 对象。
    """
    raise NotImplementedError
```

---

### 4. 测试用例

**4.1 `tests/test_token_counter.py` — 完全重写**

```python
"""Token 计数模块测试。"""
from __future__ import annotations

import pytest

from core.data.token_counter import count_tokens, slice_tokens

class TestCountTokens:
    """Token 计数测试（保留原有）。"""

    def test_empty_string(self):
        """空字符串应返回 0。"""
        assert count_tokens("") == 0

    def test_english_text(self):
        """英文文本的 token 数应大于 0。"""
        result = count_tokens("Hello, world!")
        assert result > 0

    def test_chinese_text(self):
        """中文文本的 token 数应大于 0。"""
        result = count_tokens("这是一段中文测试文本。")
        assert result > 0

    def test_longer_text_more_tokens(self):
        """更长的文本应有更多 token。"""
        short = count_tokens("短文本")
        long = count_tokens("这是一段更长的文本，包含更多的内容和信息。" * 10)
        assert long > short

class TestSliceTokens:
    """slice_tokens 核心测试。"""

    # ── 正向测试 ──

    def test_head_slice(self):
        """start=0 取首部 n 个 token，等价于旧 truncate_to_tokens。"""
        text = "这是测试文本。" * 100  # 约 500+ tokens
        n = 50
        result = slice_tokens(text, 0, n)
        assert count_tokens(result) == n
        assert text.startswith(result)

    def test_tail_slice(self):
        """从尾部截取，等价于旧 truncate_tail_tokens。"""
        text = "这是测试文本。" * 100
        total = count_tokens(text)
        n = 50
        result = slice_tokens(text, total - n, n)
        assert count_tokens(result) == n
        assert text.endswith(result)

    def test_middle_slice(self):
        """从中间位置截取，验证滑动窗口核心能力。"""
        text = "AAAA" * 20 + "BBBB" * 20 + "CCCC" * 20
        total = count_tokens(text)
        # 取中间 1/3
        start = total // 3
        length = total // 3
        result = slice_tokens(text, start, length)
        result_tokens = count_tokens(result)
        assert result_tokens == length
        # 中间段应包含 B 区域内容
        assert "BBBB" in result

    def test_full_text_slice(self):
        """start=0, length>=total 应返回完整文本。"""
        text = "Hello, world!"
        total = count_tokens(text)
        result = slice_tokens(text, 0, total + 100)
        assert result == text

    def test_consecutive_slices_cover_full_text(self):
        """连续无重叠切片拼接后应覆盖全文所有 token（无丢失）。

        fixture 设计：
        - 文本约 300 tokens
        - 窗口大小 100 tokens，步长 100（无 overlap）
        - 预期 3 个切片，拼接后 token 总数 = 原始 token 数
        """
        text = "测试内容。" * 150  # 约 300 tokens
        total = count_tokens(text)
        window = 100
        slices: list[str] = []
        pos = 0
        while pos < total:
            s = slice_tokens(text, pos, window)
            if not s:
                break
            slices.append(s)
            pos += count_tokens(s)
        # 拼接后 token 总数应等于原始 token 数
        reconstructed = "".join(slices)
        assert count_tokens(reconstructed) == total

    def test_overlap_slices_no_content_loss(self):
        """带 overlap 的滑动窗口切片不应丢失内容。

        fixture 设计：
        - 文本约 300 tokens
        - 窗口 120 tokens，步长 100（overlap 20）
        - 每个窗口实际调用 slice_tokens，收集覆盖的 token index
        - 去重后 token 总数 = 原始 token 数
        """
        text = "验证内容。" * 150  # 约 300 tokens
        total = count_tokens(text)
        window = 120
        step = 100  # overlap = 20
        covered_tokens: set[int] = set()
        pos = 0
        while pos < total:
            segment = slice_tokens(text, pos, window)
            seg_len = count_tokens(segment)
            for i in range(pos, pos + seg_len):
                covered_tokens.add(i)
            pos += step
        assert len(covered_tokens) == total

    # ── 边界测试 ──

    def test_empty_text(self):
        """空文本应返回空字符串。"""
        assert slice_tokens("", 0, 10) == ""

    def test_zero_length(self):
        """length=0 应返回空字符串。"""
        assert slice_tokens("Hello", 0, 0) == ""

    def test_negative_length(self):
        """length<0 应返回空字符串。"""
        assert slice_tokens("Hello", 0, -5) == ""

    def test_negative_start(self):
        """start<0 应修正为 0。"""
        text = "Hello, world!"
        result = slice_tokens(text, -5, 3)
        expected = slice_tokens(text, 0, 3)
        assert result == expected

    def test_start_beyond_total(self):
        """start >= total_tokens 应返回空字符串。"""
        text = "Hello"
        total = count_tokens(text)
        assert slice_tokens(text, total, 10) == ""
        assert slice_tokens(text, total + 100, 10) == ""

    def test_length_exceeds_remaining(self):
        """length 超出剩余 token 数时截取到末尾。"""
        text = "Hello, world!"
        total = count_tokens(text)
        result = slice_tokens(text, total - 2, 100)
        assert count_tokens(result) == 2

    def test_valid_utf8(self):
        """截取后的文本应是有效的 UTF-8 字符串。"""
        text = "中文混合English测试" * 50
        result = slice_tokens(text, 10, 20)
        assert isinstance(result, str)
        result.encode("utf-8")
```

**4.2 `tests/test_chunker.py` — 新增 `TestSplitTextByTokenWindow` 类**

在文件末尾新增（保留所有原有测试，更新 import）：

```python
# ── 更新 import ──
from core.data.chunker import (
    build_chunks,
    split_text_by_token_window,  # 新增
    _extract_chapter_text,
    _split_by_subheadings,
    _split_by_token_window,
)
from core.data.models import TextSegment  # 新增

# ── 纯文本窗口拆分测试 ──────────────────────────────────────────────

class TestSplitTextByTokenWindow:
    """split_text_by_token_window 公开函数测试。"""

    def test_short_text_single_segment(self):
        """短文本（<= max_tokens）应返回单个 TextSegment。"""
        text = "短文本测试。" * 10  # 约 20 tokens
        result = split_text_by_token_window(text, max_tokens=8000)
        assert len(result) == 1
        assert result[0].text == text
        assert result[0].is_last is True
        assert result[0].start_token == 0

    def test_exact_max_tokens_single_segment(self):
        """token 数恰好等于 max_tokens 时应返回单个 TextSegment。

        fixture 设计：先构造文本，计算实际 token 数，以该值作为 max_tokens。
        """
        text = "精确测试。" * 50
        total = count_tokens(text)
        result = split_text_by_token_window(text, max_tokens=total)
        assert len(result) == 1

    def test_multiple_segments_no_overlap(self):
        """无 overlap 拆分应产出多个 TextSegment，拼接后无丢失。

        fixture 设计：
        - 文本约 300 tokens
        - max_tokens=100, overlap=0
        - 预期 3 个 segment，拼接后 token 总数 = 300
        """
        text = "无损测试。" * 150  # 约 300 tokens
        total = count_tokens(text)
        result = split_text_by_token_window(text, max_tokens=100, overlap_tokens=0)
        assert len(result) >= 3
        # 拼接验证无丢失
        reconstructed = "".join(seg.text for seg in result)
        assert count_tokens(reconstructed) == total
        # 最后一个 segment 标记 is_last
        assert result[-1].is_last is True
        assert all(seg.is_last is False for seg in result[:-1])

    def test_multiple_segments_with_overlap(self):
        """带 overlap 拆分的 TextSegment 应正确重叠。

        fixture 设计：
        - 文本约 300 tokens
        - max_tokens=120, overlap=20
        - 步长=100，预期 3 个 segment
        - 每个非首 segment 的 start_token 应比前一个多 100
        """
        text = "重叠验证。" * 150  # 约 300 tokens
        total = count_tokens(text)
        result = split_text_by_token_window(text, max_tokens=120, overlap_tokens=20)
        assert len(result) >= 3
        # 验证步长 = max_tokens - overlap_tokens = 100
        for i in range(1, len(result)):
            assert result[i].start_token == result[i - 1].start_token + 100
        # 每个 segment 的 token_count <= max_tokens
        for seg in result:
            assert seg.token_count <= 120

    def test_overlap_content_matches(self):
        """相邻 segment 的重叠区域文本应完全一致。

        fixture 设计：
        - max_tokens=100, overlap=30
        - 第 i 个 segment 的尾部 30 tokens = 第 i+1 个 segment 的首部 30 tokens
        """
        text = "重叠一致性。" * 200  # 约 400 tokens
        result = split_text_by_token_window(text, max_tokens=100, overlap_tokens=30)
        assert len(result) >= 2
        for i in range(len(result) - 1):
            # 当前 segment 尾部 30 tokens
            tail = slice_tokens(result[i].text, count_tokens(result[i].text) - 30, 30)
            # 下一个 segment 首部 30 tokens
            head = slice_tokens(result[i + 1].text, 0, 30)
            assert tail == head, f"Overlap mismatch between segment {i} and {i+1}"

    # ── 边界测试 ──

    def test_empty_text_returns_empty(self):
        """空文本应返回空列表。"""
        assert split_text_by_token_window("", max_tokens=100) == []

    def test_zero_max_tokens_returns_empty(self):
        """max_tokens=0 应返回空列表。"""
        assert split_text_by_token_window("测试", max_tokens=0) == []

    def test_overlap_ge_max_tokens_auto_correct(self):
        """overlap >= max_tokens 时应自动修正为 0，不死循环。"""
        text = "防死循环。" * 100
        result = split_text_by_token_window(text, max_tokens=50, overlap_tokens=50)
        assert len(result) >= 1  # 不挂起即通过
        result2 = split_text_by_token_window(text, max_tokens=50, overlap_tokens=100)
        assert len(result2) >= 1

    def test_start_token_monotonically_increasing(self):
        """所有 segment 的 start_token 应严格递增。"""
        text = "递增验证。" * 200
        result = split_text_by_token_window(text, max_tokens=80, overlap_tokens=10)
        for i in range(1, len(result)):
            assert result[i].start_token > result[i - 1].start_token
```

**4.3 `tests/test_chunk_pipeline.py` — 新增直通路径测试**

```python
"""chunk_pipeline 直通路径测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.data.models import (
    ChunkList,
    ChunkType,
    ParsedDocument,
    ParsedPage,
)
from core.data.token_counter import count_tokens

def _make_parsed_doc(total_tokens_approx: int, source: str = "test.pdf") -> tuple[ParsedDocument, bytes]:
    """构造指定大致 token 量的 ParsedDocument 和空 PDF bytes。

    Args:
        total_tokens_approx: 目标 token 数（大致）。
        source: 来源标识。

    Returns:
        (ParsedDocument, pdf_bytes) 元组。
    """
    # 每个 "测试。" 约 2 tokens，按需重复
    repeat = max(total_tokens_approx // 2, 1)
    text = "测试。" * repeat
    page = ParsedPage(page_number=1, markdown_text=text)
    parsed = ParsedDocument(source=source, page_count=1, chunks=[page])
    # 空 PDF bytes（直通路径不需要真实 PDF 内容，但 pymupdf.open 需要）
    # 测试中 mock 掉 pymupdf.open
    return parsed, b"fake-pdf"

class TestChunkPipelineBypass:
    """chunk_pipeline 直通路径测试。"""

    @pytest.mark.asyncio
    async def test_bypass_triggered_under_3x(self):
        """文档 token 数 < 3 * max_tokens 时应走直通路径，跳过章节识别。

        fixture 设计：max_tokens=100, 文档约 200 tokens (< 300)
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(200)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf, \
             patch("core.data.chunk_pipeline.detect_chapters") as mock_detect:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=100, persist=False
            )
            # 直通路径不应调用 detect_chapters
            mock_detect.assert_not_called()
            assert isinstance(result, ChunkList)
            assert len(result.chunks) >= 1
            assert all(c.chunk_type == ChunkType.TOKEN_WINDOW for c in result.chunks)

    @pytest.mark.asyncio
    async def test_bypass_not_triggered_over_3x(self):
        """文档 token 数 >= 3 * max_tokens 时应走正常章节识别路径。

        fixture 设计：max_tokens=100, 文档约 400 tokens (>= 300)
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(400)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf, \
             patch("core.data.chunk_pipeline.detect_chapters", return_value=[]) as mock_detect, \
             patch("core.data.chunk_pipeline.build_chunks") as mock_build:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            mock_build.return_value = ChunkList(
                source=parsed.source, chunks=[], total_tokens=0, chapter_count=0
            )
            await chunk_document(
                content, parsed, max_tokens=100, persist=False
            )
            # 正常路径应调用 detect_chapters
            mock_detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_bypass_single_chunk_for_short_doc(self):
        """文档 token 数 <= max_tokens 时直通应产出单个 chunk。

        fixture 设计：max_tokens=8000, 文档约 100 tokens
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(100)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=8000, persist=False
            )
            assert len(result.chunks) == 1
            assert result.chunks[0].text == parsed.full_text

    @pytest.mark.asyncio
    async def test_bypass_chunks_cover_full_text(self):
        """直通路径产出的 chunks 应覆盖全文（无内容丢失）。

        fixture 设计：max_tokens=100, 文档约 250 tokens, overlap=20
        验证：所有 chunk 文本去除 overlap 后拼接 = 原始 full_text
        """
        from core.data.chunk_pipeline import chunk_document

        parsed, content = _make_parsed_doc(250)
        with patch("core.data.chunk_pipeline.pymupdf") as mock_pymupdf:
            mock_doc = mock_pymupdf.open.return_value
            mock_doc.close = lambda: None
            result = await chunk_document(
                content, parsed, max_tokens=100, persist=False
            )
            # 所有 chunk 的 token 数之和（含 overlap）应 >= 原始 token 数
            total_original = count_tokens(parsed.full_text)
            assert result.total_tokens >= total_original
            # 每个 chunk 不超过 max_tokens
            for c in result.chunks:
                assert c.token_count <= 100
```

---

### 4a. 静态检查与验证全红

```bash
# 类型检查
pyright core/data/token_counter.py core/data/chunker.py core/data/chunk_pipeline.py

# 运行测试，确认全部失败且均为 NotImplementedError
pytest tests/test_token_counter.py tests/test_chunker.py::TestSplitTextByTokenWindow tests/test_chunk_pipeline.py -v --tb=short 2>&1 | grep -E "NotImplementedError|FAILED|PASSED"
```

### 4b. Git 提交

```bash
git add -A && git commit -m "test: add contracts and failing tests for step2-bypass and token-refactor"
```

---

### ▶ 阶段 B：`/tdd-green` 实现

<aside>
⚠️

**阶段 B 前置检查**：确认契约文件中所有 stub 均为 `raise NotImplementedError`，不存在重复定义或残留的旧实现，避免新实现被 stub 覆盖。

</aside>

### 5. 核心实现参考

**5.1 tiktoken 切片 API**

来源：tiktoken 官方文档 / 源码（v0.7+）

```python
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

# 编码
tokens: list[int] = enc.encode("Hello, world!")

# 切片（Python 原生 list 切片）
sliced = tokens[start:start + length]

# 解码（安全，不会切断 UTF-8）
text: str = enc.decode(sliced)
```

**要点**：

- `encode()` 返回 `list[int]`，支持标准 Python 切片
- `decode()` 自动处理 UTF-8 边界，不会产生无效字符
- 编码器是线程安全的，可全局单例复用

**5.2 logfire 日志 API**

来源：logfire 官方文档（v2.x）

```python
import logfire

# 记录信息级别日志（带结构化参数）
logfire.info("直通路径: source={source}, total_tokens={total}, segments={count}",
             source=source, total=total, count=count)

# 记录 span（用于追踪函数执行）
with logfire.span("chunk_pipeline.step2_bypass"):
    ...
```

**要点**：

- 使用 f-string 风格的模板参数，logfire 自动结构化
- 生产环境通过环境变量 `LOGFIRE_TOKEN` 配置
- 开发环境无需配置，默认输出到控制台

### 6. 实现步骤

**步骤 1：实现 `slice_tokens`**

- 操作类型：修改文件
- 目标文件：`core/data/token_counter.py`
- 实现逻辑：将 `raise NotImplementedError` 替换为实际实现——调用 `_get_encoder().encode(text)` 获取 token list，进行 Python list 切片 `tokens[start:start+length]`，再 `decode()` 返回。处理边界条件（空文本、负索引、越界等）
- 同时 **删除** `truncate_to_tokens` 和 `truncate_tail_tokens` 两个函数
- 参考：5.1 tiktoken 切片 API
- 验证：`pytest tests/test_token_counter.py -v`
- Git 提交：`feat: implement slice_tokens and remove legacy truncation functions`
- depends_on: none

**步骤 2：更新 `chunker.py` 中所有旧函数调用**

- 操作类型：修改文件
- 目标文件：`core/data/chunker.py`
- 实现逻辑：
    - 删除 `from core.data.token_counter import truncate_to_tokens, truncate_tail_tokens`
    - 新增 `from core.data.token_counter import slice_tokens`
    - 将所有 `truncate_to_tokens(text, n)` 调用替换为 `slice_tokens(text, 0, n)`
    - 将所有 `truncate_tail_tokens(text, n)` 调用替换为 `slice_tokens(text, count_tokens(text) - n, n)`
- 验证：`pytest tests/test_chunker.py -v`（原有测试应全通过）
- Git 提交：与步骤 3 合并提交（步骤 2 单独替换调用点但新函数未实现，测试无法通过，需与步骤 3 构成原子变更）
- depends_on: [步骤 1]

**步骤 3：实现 `split_text_by_token_window`**

- 操作类型：修改文件
- 目标文件：`core/data/chunker.py`
- 实现逻辑：将 `raise NotImplementedError` 替换为实际实现——基于 `slice_tokens` 的滑动窗口循环。计算步长 `step = max_tokens - overlap_tokens`，从 `start=0` 循环调用 `slice_tokens(text, start, max_tokens)` 并构建 `TextSegment`。处理降级条件（空文本、overlap >= max_tokens 等）
- 参考：5.1 tiktoken 切片 API
- 验证：`pytest tests/test_chunker.py::TestSplitTextByTokenWindow -v`
- Git 提交：`feat: add split_text_by_token_window with lossless sliding window`
- depends_on: [步骤 2]

**步骤 4：实现 `_build_bypass_chunk_list` 和直通路径**

- 操作类型：修改文件
- 目标文件：`core/data/chunk_pipeline.py`
- 实现逻辑：
    - 实现 `_build_bypass_chunk_list`：遍历 `segments`，为每个 `TextSegment` 构建 `Chunk`（`chunk_type=TOKEN_WINDOW`, `chapter_path=[]`, `page_range=(1, parsed.page_count)`）
    - 在 `chunk_document` 的 Step 2 处：当 `count_tokens(parsed.full_text) < BYPASS_THRESHOLD_FACTOR * max_tokens` 时，调用 `split_text_by_token_window` 获取 segments，再调用 `_build_bypass_chunk_list` 包装为 `ChunkList`，执行持久化后直接 return（跳过后续章节识别）
    - 直通路径产出 `ChunkList` 后，**必须执行与正常路径一致的持久化逻辑**（存 DB/FS），确保后续可从本地恢复
    - 添加 logfire 日志：`"直通路径: source={source}, total_tokens={total}, segments={count}"`
- 参考：5.1 tiktoken 切片 API、5.2 logfire 日志 API
- 验证：`pytest tests/test_chunk_pipeline.py -v`
- Git 提交：`feat: implement step2 bypass path for short documents`
- depends_on: [步骤 3]

**步骤 5：修复 `_split_by_token_window` 的 overlap 内容丢失**

- 操作类型：修改文件
- 目标文件：`core/data/chunker.py`
- 实现逻辑：重构 `_split_by_token_window` 内部实现，改为调用 `split_text_by_token_window` 获取 `TextSegment` 列表，然后将每个 `TextSegment` 包装为 `Chunk`。移除原有的 `_split_oversized_paragraph` + `truncate` 组合逻辑
- 参考：5.1 tiktoken 切片 API
- 验证：`pytest tests/test_chunker.py -v`（全部测试通过，特别是 `TestSplitByTokenWindow::test_overlap_takes_tail_tokens`）
- Git 提交：`refactor: rewrite _split_by_token_window using split_text_by_token_window`
- depends_on: [步骤 3]

```
并发依赖图：
步骤 1（串行）：实现 slice_tokens + 删除旧函数 → git commit
步骤 2（串行）：更新 chunker.py 调用点 → depends_on: [1]
步骤 3（串行）：实现 split_text_by_token_window → depends_on: [2] → git commit
并发阶段：
  ├─ 步骤 4：实现直通路径 → depends_on: [3] → git commit
  └─ 步骤 5：重构 _split_by_token_window → depends_on: [3] → git commit
```

### 7. 验证清单

```bash
# 全量测试
pytest tests/ -v

# 类型检查
pyright core/data/token_counter.py core/data/chunker.py core/data/chunk_pipeline.py core/data/models.py

# 确认无残留旧函数引用
grep -rn "truncate_to_tokens\|truncate_tail_tokens" core/ tests/
# 预期：无输出
```

### 8. 测试补充（实现后评估）

- 评估 `_split_by_token_window` 重构后，原有 `TestSplitByTokenWindow::test_overlap_takes_tail_tokens` 是否仍充分覆盖 overlap 无损语义
- 若 `chunk_pipeline` 直通路径需要传入 `overlap_tokens` 参数，补充参数化测试

### 9. 技术决策说明

| 决策 | 理由 | Trade-off |
| --- | --- | --- |
| 旧函数直接删除而非 deprecated | 项目为独立开发，无外部消费者；保留会增加维护负担和误用风险 | 需一次性更新所有调用点（影响范围可控，仅 [chunker.py](http://chunker.py)） |
| 滑动窗口基于 token index 而非段落分割 | 段落分割 + 贪婪合并的方式无法保证无损覆盖（当前 bug 根因） | 失去段落边界的自然断点；但直通路径本身就是面向短文档的粗切分，段落语义交给 LLM 处理 |
| TextSegment 作为独立 dataclass | 与 Chunk 解耦，让 split_text_by_token_window 成为纯文本工具函数，可被任意模块复用 | 需要一个额外的数据结构，但结构极简（4 个字段） |
| 直通阈值 3 * max_tokens | 3 倍以内的文档最多产出 3 个窗口，章节识别收益低于开销 | 阈值为经验值，后续可基于实际摘要质量调整 |

---

## 待用户确认事项（已确认）

1. ✅ 直通阈值 `3 * max_tokens` → 提取为常量 `BYPASS_THRESHOLD_FACTOR = 3`
2. ✅ 直通路径必须走持久化逻辑（与正常路径一致），便于后续从 Notion 迁移至本地的关键信息储存
3. ✅ `_split_by_token_window` 重构后行为变化即为 overlap 内容丢失 bug 的修复，无需额外回归验证项

---

## 影响范围

| 文件 | 操作 | 说明 |
| --- | --- | --- |
| `core/data/token_counter.py` | 修改 | 新增 slice_tokens，重构现有截断函数 |
| `core/data/chunker.py` | 修改 | 提取 split_text_by_token_window 公开函数，修复 overlap 内容丢失 |
| `core/data/chunk_pipeline.py` | 修改 | 实现 Step 2 直通路径 |
| `tests/test_token_counter.py` | 新增/修改 | slice_tokens 测试用例 |
| `tests/test_chunker.py` | 新增/修改 | split_text_by_token_window 及 overlap 无损测试 |
| `tests/test_chunk_pipeline.py` | 新增/修改 | 直通路径集成测试 |