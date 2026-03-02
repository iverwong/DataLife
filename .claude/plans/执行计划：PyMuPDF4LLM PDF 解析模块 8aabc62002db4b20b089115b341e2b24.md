# 执行计划：PyMuPDF4LLM PDF 解析模块

## 1. 目标概述

将财报/公告类文本型 PDF 解析为结构化 Markdown，使用 **PyMuPDF Layout** 扩展实现自动页眉页脚过滤、表格识别和布局分析，输出按页分块的结构化数据，为 Step 2 分块策略提供标准化输入。

## 2. 前置条件

- Python 3.10+
- 现有项目中的 `core/data/pdf_split.py`（物理分割逻辑，与本模块职责分离）
- 测试用 PDF 样本：至少包含一份财报（含表格）、一份公告（纯文本为主）
- 项目统一使用 logfire 日志（已从 loguru 迁移），各模块直接 `import logfire` 调用

---

## ▶ 阶段 A：`/tdd-red` 执行以下步骤

### 3. Git 准备

```bash
git checkout main
git pull origin main
git checkout -b feat/pdf-parsing-pymupdf4llm
```

### 4. 契约定义（抽象层）

#### 4.1 项目异常基类 — `core/exceptions.py`

```python
"""DataLife 项目统一异常体系。

所有模块的自定义异常均应继承 DataLifeError，
便于上层统一捕获和日志记录。
"""

class DataLifeError(Exception):
    """DataLife 项目统一异常基类。

    Attributes:
        message: 错误描述。
        cause: 原始异常（可选）。
    """

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause

    def __str__(self) -> str:
        base = super().__str__()
        if self.cause:
            return f"{base} (caused by {type(self.cause).__name__}: {self.cause})"
        return base
```

#### 4.2 PDF 解析模块 — `core/data/pdf_parser.py`

```python
"""PDF → Markdown 解析模块。

使用 pymupdf4llm + PyMuPDF Layout 将文本型 PDF 转换为结构化 Markdown，
为后续分块和摘要做准备。

职责边界：
- 本模块只负责「内容提取」（PDF → Markdown）
- 物理分割（大文件按页拆分为子 PDF）仍由 pdf_split.py 负责
- 逻辑分块（Markdown → token 块）由 Step 2 模块负责

Layout 模式说明：
- 必须在 import pymupdf4llm 之前 import pymupdf.layout 以激活
- Layout 启用后，以下普通模式参数被忽略：
  table_strategy / margins / fontsize_limit / graphics_limit /
  hdr_info / image_size_limit / ignore_images / ignore_graphics /
  ignore_alpha / detect_bg_color / extract_words / use_glyphs
- Layout 通过 ML 模型自动识别：页眉页脚、表格、标题层级、布局区域
- Layout 新增参数：header / footer / use_ocr / ocr_language 等
"""
from __future__ import annotations

import pymupdf.layout  # noqa: F401 — 激活 Layout 模式，必须在 pymupdf4llm 之前
import pymupdf  # noqa: E402
import pymupdf4llm  # noqa: E402

import asyncio
from pathlib import Path

import logfire

from core.exceptions import DataLifeError
from core.data.models import PageChunk, PDFParseResult

# ── 异常 ─────────────────────────────────────────────
class PDFParsingError(DataLifeError):
    """PDF 解析过程中的基础异常。"""

class PDFFileNotFoundError(PDFParsingError):
    """PDF 文件路径不存在。"""

class PDFEncryptedError(PDFParsingError):
    """PDF 文件已加密且无法打开。"""

class PDFCorruptedError(PDFParsingError):
    """PDF 文件损坏或格式无效，无法解析。"""

# ── 常量 ─────────────────────────────────────────────
DEFAULT_OCR_LANGUAGE: str = "chi_sim+eng"
"""默认 OCR 语言：简体中文 + 英文（财报场景）。"""

# ── 数据结构定义在 core/data/models.py（见 4.4 节） ────

# ── 核心函数 ──────────────────────────────────────────
async def parse_pdf(
    pdf_path: str | Path,
    *,
    pages: list[int] | None = None,
    include_header_footer: bool = False,
) -> PDFParseResult:
    """将 PDF 文件解析为结构化 Markdown。

    使用 PyMuPDF Layout 模式，自动识别表格、标题层级和布局区域。
    默认过滤页眉页脚。

    内部通过 asyncio.to_thread() 将同步的 pymupdf4llm 调用
    放入线程池执行，避免阻塞事件循环。

    Args:
        pdf_path: PDF 文件路径，支持 str 或 Path。内部统一转为 Path。
        pages: 要处理的页码列表（0-based，传给 pymupdf4llm），None 表示全部页面。
            注意：返回结果中的 page_number 为 1-based（方便自然理解）。
        include_header_footer: 是否保留页眉页脚，默认 False（过滤）。
            对应 Layout 的 header / footer 参数。

    Returns:
        PDFParseResult 包含按页分块的解析结果。

    Raises:
        PDFFileNotFoundError: 文件路径不存在。
        PDFEncryptedError: PDF 已加密且无法打开。
        PDFCorruptedError: PDF 文件损坏或格式无效。
        PDFParsingError: 其它解析错误。
    """
    ...

async def parse_pdf_bytes(
    pdf_bytes: bytes,
    *,
    source: str = "unknown.pdf",
    pages: list[int] | None = None,
    include_header_footer: bool = False,
) -> PDFParseResult:
    """从内存字节流解析 PDF。

    用于从网络下载后直接解析而不落盘的场景（如巨潮/东财公告下载）。
    内部通过 asyncio.to_thread() 将同步的 pymupdf4llm 调用
    放入线程池执行，避免阻塞事件循环。

    Args:
        pdf_bytes: PDF 文件的字节内容。
        source: 来源标识（文件名或公告标题），用于日志和元信息。
        pages: 要处理的页码列表（0-based，传给 pymupdf4llm），None 表示全部。
            注意：返回结果中的 page_number 为 1-based。
        include_header_footer: 是否保留页眉页脚，默认 False。

    Returns:
        PDFParseResult 包含按页分块的解析结果。

    Raises:
        PDFCorruptedError: 字节内容为空或非有效 PDF。
        PDFEncryptedError: PDF 已加密。
        PDFParsingError: 其它解析错误。
    """
    ...

def _parse_document(
    doc: pymupdf.Document,
    *,
    source: str,
    pages: list[int] | None = None,
    include_header_footer: bool = False,
) -> PDFParseResult:
    """内部共享解析逻辑（同步）。

    由 parse_pdf 和 parse_pdf_bytes 通过 asyncio.to_thread() 调用。
    页码转换：pymupdf4llm 返回 0-based page_number，
    本函数将其转为 1-based 存入 PageChunk，方便自然理解。

    Args:
        doc: 已打开的 pymupdf.Document 对象。
        source: 来源标识。
        pages: 页码列表（0-based，直接传给 pymupdf4llm）。
        include_header_footer: 是否包含页眉页脚。

    Returns:
        PDFParseResult。
    """
    ...

def _clean_markdown(text: str) -> str:
    """清理提取的 Markdown 文本。

    处理内容：
    - 合并连续 3+ 空行为 2 个
    - 移除独立成行的纯数字页码残留（如 Layout 未完全过滤的情况）

    Layout 模式下页眉页脚已由 ML 模型自动处理，
    本函数只做轻量级后处理。

    Args:
        text: 原始 Markdown 文本。

    Returns:
        清理后的 Markdown 文本。
    """
    ...
```

#### 4.3 模块间依赖关系

```jsx
core/exceptions.py          ← DataLifeError（项目统一异常基类）
core/data/models.py         ← PageChunk, PDFParseResult（数据结构）
    └── core/data/pdf_parser.py
            ├── 激活: pymupdf.layout（Layout 模式）
            ├── 依赖: pymupdf, pymupdf4llm, logfire, asyncio
            ├── 输入: Path (文件路径) 或 bytes (字节流)
            │         来自 pdf_split.py 的物理分割结果
            │         或直接从 httpx 下载的响应体
            ├── 输出: PDFParseResult (结构化 Markdown)
            │         供 Step 2 分块模块消费
            ├── 异步: asyncio.to_thread() 包装同步 pymupdf 调用
            └── 不依赖: pdf_split.py（职责分离）
```

#### 4.4 数据结构 — `core/data/models.py`（追加）

在现有 Pydantic 模型（`StockItem`、`AnnouncementItem` 等）之后追加以下 dataclass 定义：

```python
# ── PDF 解析结果数据模型 ──────────────────────────────

from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class PageChunk:
    """单页解析结果。

    Attributes:
        page_number: 1-based 页码（方便自然理解）。
            注意：pymupdf4llm 返回 0-based，由 _parse_document() 转换为 1-based。
        markdown_text: 该页的 Markdown 文本（Layout 模式下已包含表格格式化）。
        metadata: 文档元数据，包含 file_path、page_count、page_number 等。
        toc_items: 指向该页的目录项列表，格式 [lvl, title, pagenumber(1-based)]。
        page_boxes: Layout 布局边界框列表，每项含 index / class / bbox / pos。
            class 可为 "text" / "title" / "table" / "picture" / "header" / "footer" 等。
            pos 为 tuple(start, stop)，用于从 markdown_text 中切片提取该区域文本。
    """
    page_number: int
    markdown_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    toc_items: list[list[Any]] = field(default_factory=list)
    page_boxes: list[dict[str, Any]] = field(default_factory=list)

@dataclass(frozen=True)
class PDFParseResult:
    """PDF 解析的完整结果。

    Attributes:
        source: 来源标识（文件路径字符串或自定义名称），用于日志和下游追溯。
        page_count: PDF 总页数。
        chunks: 按页分块的解析结果列表，顺序与原始页码一致。
    """
    source: str
    page_count: int
    chunks: list[PageChunk] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """拼接所有页面的 Markdown 文本，页间以双换行分隔。"""
        return "\n\n".join(chunk.markdown_text for chunk in self.chunks)
```

### 5. 测试用例

**文件**：`tests/test_data/test_pdf_parser.py`

```python
"""PDF 解析模块测试。

测试覆盖：
- 正向：正常 PDF → Markdown 转换（Layout 模式）
- 边界：空白页、单页、指定页码
- 异常：文件不存在、损坏 PDF、加密 PDF、空字节流
- 布局：页眉页脚过滤 vs 保留
- 数据结构：frozen dataclass 行为

注意：Layout 模式下 tables 元数据为空列表，
表格检测结果体现在 markdown_text 的 Markdown 表格格式中。
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from core.exceptions import DataLifeError
from core.data.models import PageChunk, PDFParseResult
from core.data.pdf_parser import (
    PDFCorruptedError,
    PDFEncryptedError,
    PDFFileNotFoundError,
    PDFParsingError,
    parse_pdf,
    parse_pdf_bytes,
)

# 标记所有测试为异步
pytestmark = pytest.mark.asyncio

# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """生成一个包含 3 页文本的测试 PDF。"""
    pdf_path = tmp_path / "test_sample.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"第 {i + 1} 页内容\n这是测试文本。")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path

@pytest.fixture
def table_pdf_path(tmp_path: Path) -> Path:
    """生成一个包含简单有线表格的测试 PDF。"""
    pdf_path = tmp_path / "test_table.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # 绘制 3x2 有线表格
    shape = page.new_shape()
    x0, y0, col_w, row_h = 72, 72, 150, 30
    rows, cols = 3, 2
    for r in range(rows + 1):
        y = y0 + r * row_h
        shape.draw_line(pymupdf.Point(x0, y), pymupdf.Point(x0 + cols * col_w, y))
    for c in range(cols + 1):
        x = x0 + c * col_w
        shape.draw_line(pymupdf.Point(x, y0), pymupdf.Point(x, y0 + rows * row_h))
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()
    page.insert_text((80, 95), "指标")
    page.insert_text((230, 95), "数值")
    page.insert_text((80, 125), "营业收入")
    page.insert_text((230, 125), "100亿")
    page.insert_text((80, 155), "净利润")
    page.insert_text((230, 155), "20亿")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path

@pytest.fixture
def sample_pdf_bytes(sample_pdf_path: Path) -> bytes:
    """返回测试 PDF 的字节内容。"""
    return sample_pdf_path.read_bytes()

@pytest.fixture
def encrypted_pdf_path(tmp_path: Path) -> Path:
    """生成一个加密的测试 PDF。"""
    pdf_path = tmp_path / "encrypted.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "加密内容")
    doc.save(
        str(pdf_path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="secret",
    )
    doc.close()
    return pdf_path

# ── parse_pdf 正向测试 ────────────────────────────────

class TestParsePdfSuccess:
    """parse_pdf 正向场景。"""

    async def test_returns_correct_page_count(self, sample_pdf_path: Path) -> None:
        """3 页 PDF 返回 page_count=3，chunks 长度=3。"""
        result = await parse_pdf(sample_pdf_path)
        assert result.page_count == 3
        assert len(result.chunks) == 3

    async def test_chunks_contain_nonempty_markdown(self, sample_pdf_path: Path) -> None:
        """每个 PageChunk 包含非空 markdown_text。"""
        result = await parse_pdf(sample_pdf_path)
        for chunk in result.chunks:
            assert isinstance(chunk, PageChunk)
            assert len(chunk.markdown_text.strip()) > 0

    async def test_page_numbers_are_1_based(self, sample_pdf_path: Path) -> None:
        """页码为 1-based，方便自然理解。

        注意：pymupdf4llm 返回 0-based，由 _parse_document 转换为 1-based。
        """
        result = await parse_pdf(sample_pdf_path)
        assert result.chunks[0].page_number == 1
        assert result.chunks[-1].page_number == 3

    async def test_specific_pages_filter(self, sample_pdf_path: Path) -> None:
        """pages=[0, 2]（0-based，传给 pymupdf4llm）只返回第 1、3 页。"""
        result = await parse_pdf(sample_pdf_path, pages=[0, 2])
        assert len(result.chunks) == 2
        assert result.chunks[0].page_number == 1
        assert result.chunks[1].page_number == 3

    async def test_source_matches_input_path(self, sample_pdf_path: Path) -> None:
        """source 与传入路径的字符串表示一致。"""
        result = await parse_pdf(sample_pdf_path)
        assert result.source == str(sample_pdf_path)

    async def test_full_text_concatenation(self, sample_pdf_path: Path) -> None:
        """full_text 拼接所有 chunk 的 markdown_text。"""
        result = await parse_pdf(sample_pdf_path)
        expected = "\n\n".join(c.markdown_text for c in result.chunks)
        assert result.full_text == expected

    async def test_accepts_string_path(self, sample_pdf_path: Path) -> None:
        """传入 str 路径也能正常工作。"""
        result = await parse_pdf(str(sample_pdf_path))
        assert result.page_count == 3

# ── parse_pdf 表格测试 ────────────────────────────────

class TestParsePdfTable:
    """表格解析测试（Layout 模式）。

    注意：Layout 模式下 page_chunks 的 tables 字段为空列表，
    表格检测体现在 markdown_text 中的 Markdown 表格格式（| 分隔符）。
    """

    async def test_table_rendered_as_markdown(self, table_pdf_path: Path) -> None:
        """含有线表格的 PDF，markdown_text 中应包含 | 分隔符。"""
        result = await parse_pdf(table_pdf_path)
        assert len(result.chunks) == 1
        # Layout 应将表格转为 Markdown 表格格式
        assert "|" in result.chunks[0].markdown_text

# ── parse_pdf 页眉页脚测试 ────────────────────────────

class TestHeaderFooterFiltering:
    """页眉页脚过滤测试（Layout 模式）。"""

    async def test_default_filters_header_footer(self, sample_pdf_path: Path) -> None:
        """默认 include_header_footer=False，应过滤页眉页脚。"""
        result = await parse_pdf(sample_pdf_path)
        assert isinstance(result, PDFParseResult)
        # 基本断言：能正常返回结果即可，具体过滤效果需真实财报验证

    async def test_include_header_footer_true(self, sample_pdf_path: Path) -> None:
        """include_header_footer=True 保留页眉页脚，内容应 >= 过滤后。"""
        result_with = await parse_pdf(sample_pdf_path, include_header_footer=True)
        result_without = await parse_pdf(sample_pdf_path, include_header_footer=False)
        # 保留页眉页脚时，文本量应 >= 过滤后
        len_with = sum(len(c.markdown_text) for c in result_with.chunks)
        len_without = sum(len(c.markdown_text) for c in result_without.chunks)
        assert len_with >= len_without

# ── parse_pdf 异常测试 ────────────────────────────────

class TestParsePdfErrors:
    """parse_pdf 异常场景。"""

    async def test_file_not_found(self, tmp_path: Path) -> None:
        """路径不存在时抛出 PDFFileNotFoundError。"""
        with pytest.raises(PDFFileNotFoundError):
            await parse_pdf(tmp_path / "nonexistent.pdf")

    async def test_corrupted_file(self, tmp_path: Path) -> None:
        """损坏文件抛出 PDFCorruptedError 或 PDFParsingError。"""
        bad_pdf = tmp_path / "corrupted.pdf"
        bad_pdf.write_bytes(b"not a valid pdf content at all")
        with pytest.raises((PDFCorruptedError, PDFParsingError)):
            await parse_pdf(bad_pdf)

    async def test_encrypted_file(self, encrypted_pdf_path: Path) -> None:
        """加密 PDF 抛出 PDFEncryptedError。"""
        with pytest.raises(PDFEncryptedError):
            await parse_pdf(encrypted_pdf_path)

    async def test_all_pdf_errors_inherit_datalife_error(self) -> None:
        """所有 PDF 异常均继承 DataLifeError。"""
        assert issubclass(PDFParsingError, DataLifeError)
        assert issubclass(PDFFileNotFoundError, PDFParsingError)
        assert issubclass(PDFEncryptedError, PDFParsingError)
        assert issubclass(PDFCorruptedError, PDFParsingError)

# ── parse_pdf_bytes 测试 ──────────────────────────────

class TestParsePdfBytes:
    """parse_pdf_bytes 测试。"""

    async def test_returns_valid_result(self, sample_pdf_bytes: bytes) -> None:
        """从 bytes 解析返回正确的 PDFParseResult。"""
        result = await parse_pdf_bytes(sample_pdf_bytes, source="test.pdf")
        assert result.page_count == 3
        assert len(result.chunks) == 3
        assert result.source == "test.pdf"

    async def test_with_specific_pages(self, sample_pdf_bytes: bytes) -> None:
        """从 bytes 解析支持 pages 参数。"""
        result = await parse_pdf_bytes(sample_pdf_bytes, pages=[0])
        assert len(result.chunks) == 1

    async def test_empty_bytes_raises_error(self) -> None:
        """空 bytes 抛出异常。"""
        with pytest.raises((PDFCorruptedError, PDFParsingError)):
            await parse_pdf_bytes(b"")

    async def test_invalid_bytes_raises_error(self) -> None:
        """非法 bytes 抛出异常。"""
        with pytest.raises((PDFCorruptedError, PDFParsingError)):
            await parse_pdf_bytes(b"invalid pdf bytes here")

# ── 数据结构测试 ──────────────────────────────────────

class TestDataStructures:
    """数据结构基本行为。"""

    async def test_page_chunk_is_frozen(self) -> None:
        """PageChunk 不可变。"""
        chunk = PageChunk(page_number=1, markdown_text="test")
        with pytest.raises(AttributeError):
            chunk.page_number = 2  # type: ignore

    async def test_parse_result_full_text_empty(self) -> None:
        """空 chunks 的 full_text 为空字符串。"""
        result = PDFParseResult(source="test.pdf", page_count=0)
        assert result.full_text == ""

    async def test_parse_result_is_frozen(self) -> None:
        """PDFParseResult 不可变。"""
        result = PDFParseResult(source="test.pdf", page_count=0)
        with pytest.raises(AttributeError):
            result.page_count = 5  # type: ignore

    async def test_page_chunk_default_fields(self) -> None:
        """PageChunk 默认字段为空集合。"""
        chunk = PageChunk(page_number=1, markdown_text="text")
        assert chunk.metadata == {}
        assert chunk.toc_items == []
        assert chunk.page_boxes == []
```

### 5a. 静态检查与验证全红

```bash
# 类型检查
pyright core/exceptions.py core/data/pdf_parser.py core/data/models.py tests/test_data/test_pdf_parser.py

# Linter
ruff check core/exceptions.py core/data/pdf_parser.py core/data/models.py tests/test_data/test_pdf_parser.py

# 运行测试 — 确认全红（所有测试 FAIL）
pytest tests/test_data/test_pdf_parser.py -v
```

### 5b. Git 提交

```bash
git add core/exceptions.py core/data/pdf_parser.py core/data/models.py tests/test_data/test_pdf_parser.py
git commit -m "test: add contracts and failing tests for PDF parsing module"
```

---

## ▶ 阶段 B：`/tdd-green` 执行以下步骤

### 6. 核心实现参考

> **来源**：PyMuPDF4LLM v0.2.8 官方文档 + PyMuPDF Layout 文档
> 

> **文档 URL**：[pymupdf4llm API](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html)
> 

#### 6.1 安装

```bash
# pymupdf4llm（自动安装 pymupdf 依赖）
pip install pymupdf4llm>=0.2.8

# PyMuPDF Layout 扩展（免费，独立于 Pro）
pip install pymupdf-layout
```

#### 6.2 Layout 模式激活

```python
# ⚠️ 必须在 import pymupdf4llm 之前 import pymupdf.layout
import pymupdf.layout  # 激活 Layout 驱动的提取模式
import pymupdf4llm

# 激活后，pymupdf4llm 会自动切换为 Layout 驱动模式
# 以下普通模式参数将被忽略：
#   table_strategy, margins, fontsize_limit, graphics_limit,
#   hdr_info, image_size_limit, ignore_images, ignore_graphics,
#   ignore_alpha, detect_bg_color, extract_words, use_glyphs
```

#### 6.3 核心 API：`to_markdown()`（Layout 模式）

```python
import pymupdf.layout  # noqa: F401
import pymupdf
import pymupdf4llm

# ── 从文件路径解析 ──
chunks: list[dict] = pymupdf4llm.to_markdown(
    "report.pdf",
    page_chunks=True,       # 按页分块，返回 list[dict]
    header=False,            # Layout: 过滤页眉
    footer=False,            # Layout: 过滤页脚
    force_text=True,         # 被图形遮挡的文本也强制提取
    show_progress=False,
)

# ── 从 bytes 解析 ──
pdf_bytes: bytes = download_pdf()
doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

chunks = pymupdf4llm.to_markdown(
    doc,                     # 传入 Document 对象
    page_chunks=True,
    header=False,
    footer=False,
    force_text=True,
    show_progress=False,
)
doc.close()

# ── 每个 chunk 的结构（Layout 模式）──
# {
#   "metadata": {"file_path": str, "page_count": int, "page_number": int},
#   "toc_items": [[lvl, title, pagenumber], ...],  # 1-based 页码
#   "tables": [],       # ⚠️ Layout 模式下始终为空列表
#   "images": [],       # ⚠️ Layout 模式下始终为空列表
#   "graphics": [],     # ⚠️ Layout 模式下始终为空列表
#   "text": "该页的 Markdown 文本（表格已格式化为 Markdown 表格）",
#   "words": [],        # ⚠️ Layout 模式下始终为空列表
#   "page_boxes": [     # ✅ Layout 专属：布局边界框
#       {"index": 0, "class": "title", "bbox": (x0, y0, x1, y1), "pos": (start, stop)},
#       {"index": 1, "class": "text", "bbox": ..., "pos": (start, stop)},
#       {"index": 2, "class": "table", "bbox": ..., "pos": (start, stop)},
#       ...
#   ],
# }
```

#### 6.4 使用 `pymupdf.Document` 对象

```python
import pymupdf

# 从文件路径打开
doc = pymupdf.open(str(path))  # ⚠️ 必须传 str，不能传 Path

# 从 bytes 打开
doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

# 检查加密状态
if doc.is_encrypted:
    if not doc.authenticate(""):  # 尝试空密码
        doc.close()
        raise PDFEncryptedError("PDF 已加密")

# 获取页数
total_pages = doc.page_count

# 用完必须关闭
doc.close()
```

#### 6.5 指定页码范围

```python
# 0-based 页码
chunks = pymupdf4llm.to_markdown(doc, pages=[0, 5, 10], page_chunks=True)

# 处理前 10 页
chunks = pymupdf4llm.to_markdown(doc, pages=list(range(10)), page_chunks=True)
```

#### 6.6 Layout 专属：OCR 能力

```python
# Layout 自动判定是否需要 OCR（默认 use_ocr=True）
# 对于文本型 PDF 通常不会触发 OCR

# 如需指定中文 OCR 语言（需系统安装 Tesseract + chi_sim 语言包）
chunks = pymupdf4llm.to_markdown(
    doc,
    page_chunks=True,
    header=False,
    footer=False,
    ocr_language="chi_sim+eng",  # 简体中文 + 英文
)
```

#### 6.7 常见陷阱与注意事项

1. **`import pymupdf.layout` 必须在 `import pymupdf4llm` 之前**，否则 Layout 不会激活
2. **`doc` 参数不接受 `pathlib.Path`**，必须先转为 `str` 或通过 `pymupdf.open()` 创建 `Document`
3. **Layout 模式下 `tables` / `images` / `graphics` / `words` 均为空列表**，不要依赖这些字段
4. **Layout 模式下表格检测由 ML 模型完成**，无需也无法指定 `table_strategy`
5. **`page_chunks=True` 时返回 `list[dict]`**，不是 `str`
6. **Layout 的 `page_boxes` 提供布局语义**，`class` 字段标识区域类型（title / text / table / picture / header / footer）
7. **`force_text=True` 在 Layout 下仍有效**：被 "picture" 类边界框覆盖的文本会在图片引用后输出

### 7. 实现步骤

#### 步骤 7.1：安装依赖

- **操作**：修改文件 `pyproject.toml`（或 `requirements.txt`）
- **描述**：添加依赖：
    - `pymupdf4llm>=0.2.8`
    - `pymupdf-layout`（Layout 扩展）
- **验证**：`pip install -e .` 成功，`python -c "import pymupdf.layout; import pymupdf4llm; print('OK')"`
- **Git**：暂不提交
- **depends_on**：none

#### 步骤 7.2：创建项目异常基类

- **操作**：创建文件 `core/exceptions.py`
- **描述**：实现 `DataLifeError` 基类（见第 4.1 节完整代码），包含 `message` 和可选 `cause` 属性，`__str__` 方法展示因果链
- **验证**：`python -c "from core.exceptions import DataLifeError; print('OK')"`
- **Git**：暂不提交
- **depends_on**：none
- **可并发**：与步骤 7.1 并发

#### 步骤 7.2a：追加数据模型到 `core/data/models.py`

- **操作**：修改文件 `core/data/models.py`
- **描述**：在现有 Pydantic 模型之后追加 `PageChunk` 和 `PDFParseResult` 两个 frozen dataclass（见第 4.4 节完整代码）
- **验证**：`python -c "from core.data.models import PageChunk, PDFParseResult; print('OK')"`
- **Git**：暂不提交
- **depends_on**：none
- **可并发**：与步骤 7.1、7.2 并发

#### 步骤 7.3：实现 `_parse_document()` + `_clean_markdown()` 共享逻辑

- **操作**：修改文件 `core/data/pdf_parser.py`
- **描述**：实现内部函数 `_parse_document()` 和 `_clean_markdown()`，作为 `parse_pdf` 和 `parse_pdf_bytes` 的核心：
    1. 调用 `pymupdf4llm.to_markdown(doc, page_chunks=True, header=include_header_footer, footer=include_header_footer, force_text=True, show_progress=False, pages=pages)`
    2. 将返回的 `list[dict]` 逐项转换为 `PageChunk`，从 chunk 中提取 `metadata`、`toc_items`、`page_boxes`、`text`；将 pymupdf4llm 返回的 0-based `page_number` 转换为 **1-based**
    3. 对 `text` 调用 `_clean_markdown()` 做后处理（合并连续空行、移除残留页码行）
    4. 组装 `PDFParseResult(source=source, page_count=doc.page_count, chunks=...)` 并返回
    5. 使用 `logfire.info` / `logfire.debug` 记录解析进度
- **参考**：6.3 核心 API（Layout 模式）
- **验证**：此步骤不直接验证，由 7.4 和 7.5 间接验证
- **Git**：暂不提交
- **depends_on**：7.1, 7.2, 7.2a

#### 步骤 7.4：实现 `parse_pdf()`

- **操作**：修改文件 `core/data/pdf_parser.py`
- **描述**：实现 `async def parse_pdf()` 函数：
    1. 将 `pdf_path` 统一转为 `Path` 对象
    2. 检查 `path.exists()`，不存在则抛 `PDFFileNotFoundError`
    3. 使用 `pymupdf.open(str(path))` 打开文档（**必须传 str**，参考 6.4）
    4. 检查 `doc.is_encrypted`，尝试空密码认证，失败则 `doc.close()` 后抛 `PDFEncryptedError`
    5. 在 `try/finally` 中通过 `await asyncio.to_thread(_parse_document, doc, ...)` 调用，`source=str(path)`
    6. 捕获 `RuntimeError` / `ValueError` 等 pymupdf 原生异常，包装为 `PDFCorruptedError`
    7. `finally` 确保 `doc.close()`
- **参考**：6.4 使用 Document 对象
- **验证**：`pytest tests/test_data/test_pdf_parser.py::TestParsePdfSuccess tests/test_data/test_pdf_parser.py::TestParsePdfErrors -v`
- **Git**：提交 `feat: implement parse_pdf with Layout mode`
- **depends_on**：7.3

#### 步骤 7.5：实现 `parse_pdf_bytes()`

- **操作**：修改文件 `core/data/pdf_parser.py`
- **描述**：实现 `async def parse_pdf_bytes()` 函数：
    1. 检查 `pdf_bytes` 是否为空，为空则抛 `PDFCorruptedError("PDF 内容为空")`
    2. 使用 `pymupdf.open(stream=pdf_bytes, filetype="pdf")` 创建 Document（参考 6.4）
    3. 加密检查同 7.4
    4. 通过 `await asyncio.to_thread(_parse_document, doc, ...)` 调用，`source=source`
    5. 异常处理和资源释放同 7.4
- **参考**：6.4 使用 Document 对象
- **验证**：`pytest tests/test_data/test_pdf_parser.py::TestParsePdfBytes -v`
- **Git**：提交 `feat: implement parse_pdf_bytes for in-memory parsing`
- **depends_on**：7.3

<aside>
⚡

**并发策略**：

**阶段 1（并发）**：

- Sub-agent A：步骤 7.1（安装依赖）
- Sub-agent B：步骤 7.2（创建异常基类）
- Sub-agent C：步骤 7.2a（追加数据模型到 [models.py](http://models.py)）

**阶段 2（串行）**：步骤 7.3（共享逻辑 `_parse_document` + `_clean_markdown`）

**阶段 3**：步骤 7.4 和 7.5 **串行执行**（操作同一文件 `pdf_parser.py`）

**阶段 4（串行）**：步骤 8 验证清单

</aside>

### 8. 验证清单

```bash
# 1. 全量测试
pytest tests/test_data/test_pdf_parser.py -v --tb=short

# 2. 项目回归测试 — 确保无破坏
pytest tests/ -v --tb=short

# 3. 类型检查
pyright core/exceptions.py core/data/pdf_parser.py core/data/models.py tests/test_data/test_pdf_parser.py

# 4. Linter
ruff check core/exceptions.py core/data/pdf_parser.py core/data/models.py tests/test_data/test_pdf_parser.py

# 5. 真实 PDF 验证（手动）
python scripts/test_pdf_parse.py <普通公告.pdf>
python scripts/test_pdf_parse.py <含表格财报.pdf>

# 6. 覆盖率（可选）
pytest tests/test_data/test_pdf_parser.py --cov=core.data.pdf_parser --cov-report=term-missing

# 7. Git 状态
git log --oneline  # 确认 commit 记录清晰
git status         # 无未提交变更
```

### 9. 测试补充

基于实现过程中的发现，评估是否需要补充：

- [ ]  大文件性能测试（200+ 页财报的处理时间和内存占用）
- [ ]  Layout 对合并单元格表格的 Markdown 输出格式
- [ ]  跨页表格的处理行为
- [ ]  含中文路径的 PDF 解析
- [ ]  `page_boxes` 布局分类的准确性验证
- [ ]  Layout 的 OCR 触发条件测试（扫描件 vs 文本型）
- [ ]  `include_header_footer=True/False` 在真实财报上的效果对比

### 10. 技术决策说明

| 决策 | 选择 | 理由 | Trade-off |
| --- | --- | --- | --- |
| 启用 PyMuPDF Layout | `pip install pymupdf-layout` | Layout 提供 ML 驱动的页眉页脚识别、表格检测和布局分析，比基础模式更适合财报/公告场景 | 引入额外依赖，处理速度可能略慢（ML 推理）。但财报处理非实时场景，可接受 |
| 页眉页脚策略 | 解析时直接过滤（`header=False, footer=False`） | Layout 的 ML 模型能自动识别页眉页脚区域，无需依赖固定边距或后处理 | ML 识别可能有误判，但比 margins 固定裁切更通用 |
| 项目异常基类 | 新建 `core/exceptions.py` → `DataLifeError` | 统一异常体系，便于上层（FastAPI / 调度器）统一捕获和日志 | 现有模块需逐步迁移（本次不动现有代码） |
| 路径类型 | `pathlib.Path` | 与项目后续统一使用 Path 的方向一致，API 层支持 `str | Path` 兼容 | 内部统一转 Path，[pymupdf.open](http://pymupdf.open) 需再转 str |
| 数据结构 | frozen dataclass（定义在 `core/data/models.py`） | 解析结果不应被下游修改，保证数据流的不可变性。放入 [models.py](http://models.py) 便于跨模块引用，后期模型增多再分模块 | 如需修改需创建新实例 |
| 新建 `pdf_parser.py` | 独立于 `pdf_split.py` | 职责分离：pdf_split 负责物理分割（PDF → 多个子 PDF），pdf_parser 负责内容提取（PDF → Markdown） | 两个模块间无代码复用，但数据流清晰 |
| 日志 | 直接使用 `logfire` | 项目已从 loguru 统一迁移到 logfire，各模块直接 `import logfire` 调用，与 `pdf_split.py` 等现有模块一致 | — |
| 异步包装 | `asyncio.to_thread()` 包装同步 pymupdf 调用 | pymupdf4llm 是同步库，使用 `to_thread` 放入线程池避免阻塞事件循环，与项目异步架构一致 | 线程池有上限，但 PDF 解析非高并发场景，可接受 |
| 页码基准 | 1-based（项目内部），0-based（传给 pymupdf4llm） | 1-based 方便自然理解和日志展示，与 pymupdf4llm 的 toc_items 页码基准一致 | 需在 `_parse_document` 中做 +1 转换，docstring 中明确标注基准 |

---

<aside>
✅

[**conftest.py](http://conftest.py) 已确认**（`tests/conftest.py`）：

- `event_loop`：session scope，供异步测试共享事件循环
- `test_env`：session scope，从 `.dev.env` 加载 `NOTION_TOKEN` / `FLOW_DATABASE` / `STOCK_POOL`
- `in_memory_db`：function scope，patch `core.db._get_db`，提供含 `update_records` + `hash` 表的内存 SQLite

`test_pdf_parser.py` 的测试均为**异步**（使用 `pytestmark = pytest.mark.asyncio`），不依赖 DB，与现有 conftest 的 `event_loop` fixture 兼容。

</aside>