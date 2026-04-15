"""AnnouncementCache 单元测试。

覆盖范围：缓存命中/未命中、grep、read_lines、PDF 解析。
外部依赖：CninfoClient.download_pdf mock，文件系统使用 tmp_path。
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tools.services.announcement_cache import AnnouncementCache
from core.tools.services.cninfo_client import CninfoClient
from core.tools.services.types import GrepMatch

# ── Helpers ────────────────────────────────────────────────────────────────

SAMPLE_PDF_BYTES = b"%PDF-1.4 mock pdf content"


def _make_cache_file(cache_dir: Path, announcement_id: str, content: str) -> Path:
    """在 cache_dir 下创建公告缓存文件，返回文件路径。"""
    path = cache_dir / f"{announcement_id}.txt"
    _ = path.write_text(content, encoding="utf-8")
    return path


# ── TestEnsureCached ───────────────────────────────────────────────────────


class TestEnsureCached:
    """ensure_cached 测试。"""

    @pytest.mark.asyncio
    async def test_already_cached(self, tmp_path: Path) -> None:
        """Given: 缓存文件已存在
        When: 调用 ensure_cached
        Then: 不调用 download，直接返回路径"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_001"
        _ = _make_cache_file(tmp_path, ann_id, "already cached content")

        result = await cache.ensure_cached(ann_id, "https://example.com/file.pdf")

        assert result == tmp_path / f"{ann_id}.txt"
        mock_client.download_pdf.assert_not_called()  # pyright: ignore[reportAny]

    @pytest.mark.asyncio
    async def test_download_and_cache(self, tmp_path: Path) -> None:
        """Given: 缓存文件不存在
        When: 调用 ensure_cached
        Then: 调用 download_pdf → _parse_pdf_to_text → 写入 .txt"""
        mock_client = MagicMock(spec=CninfoClient)
        mock_client.download_pdf = AsyncMock(return_value=SAMPLE_PDF_BYTES)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_002"
        pdf_url = "https://example.com/ann_002.pdf"

        with patch.object(
            AnnouncementCache,
            "_parse_pdf_to_text",
            return_value="# Markdown content\nLine two",
        ):
            result = await cache.ensure_cached(ann_id, pdf_url)

        assert result == tmp_path / f"{ann_id}.txt"
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "# Markdown content\nLine two"
        mock_client.download_pdf.assert_awaited_once_with(pdf_url)  # pyright: ignore[reportAny]


# ── TestGrep ───────────────────────────────────────────────────────────────


class TestGrep:
    """grep 测试。"""

    def test_finds_matches_with_context(self, tmp_path: Path) -> None:
        """Given: 缓存文件含 3 处关键词
        When: 调用 grep(pattern, context_lines=2)
        Then: 返回 3 个 GrepMatch，各含 2 行上下文"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_003"
        content = "\n".join(
            [
                "header line 1",
                "header line 2",
                ">>> keyword here at line 3 <<<",
                "trailing line 4",
                ">>> another keyword at line 5 <<<",
                "middle line 6",
                ">>> third keyword at line 7 <<<",
                "footer line 8",
            ]
        )
        _ = _make_cache_file(tmp_path, ann_id, content)

        matches = cache.grep(ann_id, "keyword", context_lines=2)

        assert len(matches) == 3
        for m in matches:
            assert isinstance(m, GrepMatch)
            assert m.line_number in (3, 5, 7)
            assert len(m.context_before) <= 2
            assert len(m.context_after) <= 2

    def test_no_matches(self, tmp_path: Path) -> None:
        """Given: 缓存文件不含关键词
        When: 调用 grep
        Then: 返回空列表"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_004"
        _ = _make_cache_file(tmp_path, ann_id, "nothing interesting here\njust regular text")

        matches = cache.grep(ann_id, "nonexistent_pattern_xyz")

        assert matches == []

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Given: 公告未缓存
        When: 调用 grep
        Then: 抛出 FileNotFoundError"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        with pytest.raises(FileNotFoundError):
            _ = cache.grep("nonexistent_id", "pattern")


# ── TestGrepHeadLimitDefault ───────────────────────────────────────────────


class TestGrepHeadLimitDefault:
    """GrepInput head_limit 默认值测试。

    覆盖：默认值已从 50 改为 30。
    """

    def test_head_limit_default_is_30(self) -> None:
        """Given: 不指定 head_limit
        When: 构造 GrepInput
        Then: head_limit == 30"""
        from core.tools.services.types import GrepInput

        inp = GrepInput(announcement_id="ann_001", pattern="test")
        assert inp.head_limit == 30


# ── TestReadLines ──────────────────────────────────────────────────────────


class TestReadLines:
    """read_lines 测试。"""

    def test_valid_range(self, tmp_path: Path) -> None:
        """Given: 缓存文件有 100 行
        When: 调用 read_lines(offset=1, limit=10)
        Then: 返回前 10 行，附行号标注"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_005"
        lines = [f"line content {i}" for i in range(1, 101)]
        _ = _make_cache_file(tmp_path, ann_id, "\n".join(lines))

        result = cache.read_lines(ann_id, offset=1, limit=10)

        assert "共 100 行" in result
        assert "显示 1~10 行" in result
        assert "L1: line content 1" in result
        assert "L10: line content 10" in result
        assert "L11:" not in result

    def test_partial_out_of_range(self, tmp_path: Path) -> None:
        """Given: 缓存文件有 50 行
        When: 调用 read_lines(offset=40, limit=20)
        Then: 返回 40~50 行（截断至实际行数）"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_006"
        lines = [f"line content {i}" for i in range(1, 51)]
        _ = _make_cache_file(tmp_path, ann_id, "\n".join(lines))

        result = cache.read_lines(ann_id, offset=40, limit=20)

        assert "共 50 行" in result
        assert "显示 40~50 行" in result
        assert "L40: line content 40" in result
        assert "L50: line content 50" in result
        assert "L51:" not in result

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Given: 公告未缓存
        When: 调用 read_lines
        Then: 抛出 FileNotFoundError"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        with pytest.raises(FileNotFoundError):
            _ = cache.read_lines("nonexistent_id", offset=1, limit=10)


# ── TestReadHardLimit ──────────────────────────────────────────────────────


class TestReadHardLimit:
    """read_lines 硬上限测试。

    覆盖：limit 参数硬上限 500 行，防止 LLM 一次性读取整篇公告。
    """

    def test_hard_limit_caps_at_500(self, tmp_path: Path) -> None:
        """Given: 缓存文件有 1000 行，调用方传入 limit=10000
        When: 调用 read_lines(offset=1, limit=10000)
        Then: 实际只返回前 500 行（硬上限截断）"""
        mock_client = MagicMock(spec=CninfoClient)
        cache = AnnouncementCache(client=mock_client, cache_dir=tmp_path)

        ann_id = "ann_hard_limit"
        lines = [f"line content {i}" for i in range(1, 1001)]
        _ = _make_cache_file(tmp_path, ann_id, "\n".join(lines))

        result = cache.read_lines(ann_id, offset=1, limit=10000)

        assert "显示 1~500 行" in result
        assert "L500:" in result
        assert "L501:" not in result


# ── TestParsePdfToText ─────────────────────────────────────────────────────


class TestParsePdfToText:
    """_parse_pdf_to_text 静态方法测试。"""

    def test_parse_valid_pdf(self) -> None:
        """Given: 有效 PDF bytes
        When: 调用 _parse_pdf_to_text
        Then: 返回非空 Markdown 文本"""
        # 使用 mock 避免依赖真实 PDF 文件和外部库
        mock_doc = MagicMock()
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=None)

        with (
            patch(
                "core.tools.services.announcement_cache.pymupdf.open",
            ) as mock_open,
            patch(
                "core.tools.services.announcement_cache.pymupdf4llm.to_markdown",
            ) as mock_to_markdown,
        ):
            mock_open.return_value = mock_doc
            mock_to_markdown.return_value = "# Header\n\nSome content here"

            result = AnnouncementCache._parse_pdf_to_text(SAMPLE_PDF_BYTES)  # pyright: ignore[reportPrivateUsage]

            mock_open.assert_called_once_with(stream=SAMPLE_PDF_BYTES, filetype="pdf")
            mock_to_markdown.assert_called_once_with(doc=mock_doc)
            assert result == "# Header\n\nSome content here"
            assert len(result) > 0

    def test_parse_empty_pdf(self) -> None:
        """Given: 空白页 PDF
        When: 调用 _parse_pdf_to_text
        Then: 返回空字符串或最小文本"""
        mock_doc = MagicMock()
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=None)

        with (
            patch(
                "core.tools.services.announcement_cache.pymupdf.open",
            ) as mock_open,
            patch(
                "core.tools.services.announcement_cache.pymupdf4llm.to_markdown",
            ) as mock_to_markdown,
        ):
            mock_open.return_value = mock_doc
            mock_to_markdown.return_value = ""

            result = AnnouncementCache._parse_pdf_to_text(b"%PDF-1.4 empty")  # pyright: ignore[reportPrivateUsage]

            assert result == ""
