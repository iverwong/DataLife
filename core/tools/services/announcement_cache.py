"""公告全文本地缓存服务。

策略：PDF 下载 → PyMuPDF4LLM 解析为 Markdown → 存储为 .txt。
支持 grep 搜索和按行读取。
"""

from __future__ import annotations

from pathlib import Path

from core.tools.services.cninfo_client import CninfoClient
from core.tools.services.types import GrepMatch

DEFAULT_CACHE_DIR = Path("data/cache/announcements")


class AnnouncementCache:
    """公告全文本地缓存。

    文件布局：{cache_dir}/{announcement_id}.txt
    """

    def __init__(
        self,
        client: CninfoClient,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ) -> None:
        raise NotImplementedError

    async def ensure_cached(
        self, announcement_id: str, pdf_url: str
    ) -> Path:
        """确保公告全文已缓存，返回文件路径。

        已缓存则直接返回；否则下载并解析。

        Args:
            announcement_id: 公告 ID。
            pdf_url: PDF 下载链接。

        Returns:
            缓存文件路径。
        """
        raise NotImplementedError

    def grep(
        self,
        announcement_id: str,
        pattern: str,
        ignore_case: bool = True,
        context_lines: int = 3,
        before_context: int | None = None,
        after_context: int | None = None,
    ) -> list[GrepMatch]:
        """在已缓存公告中用正则表达式搜索。

        借鉴 Claude Code Grep 设计：支持正则、大小写、
        前后上下文分别控制。

        Args:
            announcement_id: 公告 ID（必须已缓存）。
            pattern: 正则表达式搜索模式。
            ignore_case: 不区分大小写，默认 True。
            context_lines: 上下文行数，默认 3（前后对称）。
            before_context: 匹配前的行数（覆盖 context_lines）。
            after_context: 匹配后的行数（覆盖 context_lines）。

        Returns:
            命中结果列表。

        Raises:
            FileNotFoundError: 公告未缓存。
            re.error: 无效的正则表达式。
        """
        raise NotImplementedError

    def read_lines(
        self,
        announcement_id: str,
        offset: int = 1,
        limit: int = 200,
    ) -> str:
        """读取已缓存公告的指定行范围。

        借鉴 Claude Code Read 设计：offset + limit 语义。

        Args:
            announcement_id: 公告 ID（必须已缓存）。
            offset: 起始行号（从 1 开始，默认 1）。
            limit: 读取行数限制（默认 200）。

        Returns:
            指定行范围的文本，附带行号标注和总行数信息。

        Raises:
            FileNotFoundError: 公告未缓存。
        """
        raise NotImplementedError

    def get_total_lines(self, announcement_id: str) -> int:
        """获取已缓存公告的总行数。

        Args:
            announcement_id: 公告 ID（必须已缓存）。

        Returns:
            总行数。
        """
        raise NotImplementedError

    async def _download_and_parse(
        self, announcement_id: str, pdf_url: str
    ) -> Path:
        """下载 PDF 并解析为文本，存储到缓存目录。

        使用 asyncio.to_thread 包装同步的 PDF 解析。

        Args:
            announcement_id: 公告 ID。
            pdf_url: PDF 下载链接。

        Returns:
            缓存文件路径。
        """
        raise NotImplementedError

    @staticmethod
    def _parse_pdf_to_text(pdf_bytes: bytes) -> str:
        """使用 PyMuPDF4LLM 将 PDF 转为 Markdown 文本。

        同步 API，调用方应用 asyncio.to_thread() 包装。

        Args:
            pdf_bytes: PDF 二进制内容。

        Returns:
            Markdown 格式文本。
        """
        raise NotImplementedError

    def _get_cache_path(self, announcement_id: str) -> Path:
        """获取公告缓存文件路径。"""
        raise NotImplementedError
