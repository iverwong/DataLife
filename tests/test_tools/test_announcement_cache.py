"""AnnouncementCache 单元测试。

覆盖范围：缓存命中/未命中、grep、read_lines、PDF 解析。
外部依赖：CninfoClient.download_pdf mock，文件系统使用 tmp_path。
"""

import pytest

class TestEnsureCached:
    """ensure_cached 测试。"""

    @pytest.mark.asyncio
    async def test_already_cached(self):
        """Given: 缓存文件已存在
        When: 调用 ensure_cached
        Then: 不调用 download，直接返回路径"""

    @pytest.mark.asyncio
    async def test_download_and_cache(self):
        """Given: 缓存文件不存在
        When: 调用 ensure_cached
        Then: 调用 download_pdf → _parse_pdf_to_text → 写入 .txt"""

class TestGrep:
    """grep 测试。"""

    def test_finds_matches_with_context(self):
        """Given: 缓存文件含 3 处关键词
        When: 调用 grep(pattern, context_lines=2)
        Then: 返回 3 个 GrepMatch，各含 2 行上下文"""

    def test_no_matches(self):
        """Given: 缓存文件不含关键词
        When: 调用 grep
        Then: 返回空列表"""

    def test_file_not_found(self):
        """Given: 公告未缓存
        When: 调用 grep
        Then: 抛出 FileNotFoundError"""

class TestReadLines:
    """read_lines 测试。"""

    def test_valid_range(self):
        """Given: 缓存文件有 100 行
        When: 调用 read_lines(offset=1, limit=10)
        Then: 返回前 10 行，附行号标注"""

    def test_partial_out_of_range(self):
        """Given: 缓存文件有 50 行
        When: 调用 read_lines(offset=40, limit=20)
        Then: 返回 40~50 行（截断至实际行数）"""

    def test_file_not_found(self):
        """Given: 公告未缓存
        When: 调用 read_lines
        Then: 抛出 FileNotFoundError"""

class TestParsePdfToText:
    """_parse_pdf_to_text 静态方法测试。"""

    def test_parse_valid_pdf(self):
        """Given: 有效 PDF bytes
        When: 调用 _parse_pdf_to_text
        Then: 返回非空 Markdown 文本"""

    def test_parse_empty_pdf(self):
        """Given: 空白页 PDF
        When: 调用 _parse_pdf_to_text
        Then: 返回空字符串或最小文本"""
