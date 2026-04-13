"""公告全文本地缓存服务。

策略：PDF 下载 → PyMuPDF4LLM 解析为 Markdown → 存储为 .txt。
支持 grep 搜索和按行读取。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pymupdf
import pymupdf4llm

from typing import cast

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
        self._client: CninfoClient = client
        self._cache_dir: Path = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, announcement_id: str) -> Path:
        """获取公告缓存文件路径。"""
        return self._cache_dir / f"{announcement_id}.txt"

    async def ensure_cached(
        self, announcement_id: str, pdf_url: str
    ) -> Path:
        """确保公告全文已缓存，返回文件路径。

        已缓存则直接返回；否则下载并解析。
        """
        path = self._get_cache_path(announcement_id)
        if path.exists():
            return path
        return await self._download_and_parse(announcement_id, pdf_url)

    async def _download_and_parse(
        self, announcement_id: str, pdf_url: str
    ) -> Path:
        """下载 PDF 并解析为文本，存储到缓存目录。"""
        pdf_bytes = await self._client.download_pdf(pdf_url)
        text = await asyncio.to_thread(
            self._parse_pdf_to_text, pdf_bytes
        )
        path = self._get_cache_path(announcement_id)
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def _parse_pdf_to_text(pdf_bytes: bytes) -> str:
        """使用 PyMuPDF4LLM 将 PDF 转为 Markdown 文本。"""
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        result = pymupdf4llm.to_markdown(doc=doc)
        return cast(str, result)

    def grep(
        self,
        announcement_id: str,
        pattern: str,
        ignore_case: bool = True,
        context_lines: int = 3,
        before_context: int | None = None,
        after_context: int | None = None,
    ) -> list[GrepMatch]:
        """在已缓存公告中用正则表达式搜索。"""
        path = self._get_cache_path(announcement_id)
        if not path.exists():
            raise FileNotFoundError(
                f"公告 {announcement_id} 未缓存，请先调用 search_announcements"
            )

        lines = path.read_text(encoding="utf-8").splitlines()
        flags = re.IGNORECASE if ignore_case else 0
        compiled = re.compile(pattern, flags)

        _before = before_context if before_context is not None else context_lines
        _after = after_context if after_context is not None else context_lines

        matches: list[GrepMatch] = []
        for i, line in enumerate(lines, start=1):
            if compiled.search(line):
                start = max(0, i - 1 - _before)
                end = min(len(lines), i - 1 + 1 + _after)
                context_before = lines[start : i - 1]
                context_after = lines[i : end]
                matches.append(
                    GrepMatch(
                        line_number=i,
                        content=line,
                        context_before=context_before,
                        context_after=context_after,
                    )
                )
        return matches

    def read_lines(
        self,
        announcement_id: str,
        offset: int = 1,
        limit: int = 200,
    ) -> str:
        """读取已缓存公告的指定行范围。"""
        path = self._get_cache_path(announcement_id)
        if not path.exists():
            raise FileNotFoundError(
                f"公告 {announcement_id} 未缓存，请先调用 search_announcements"
            )

        lines = path.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(len(lines), start + limit)
        selected = lines[start:end]

        header = f"--- 共 {total} 行，显示 {offset}~{min(offset + limit - 1, total)} 行 ---\n"
        body = "\n".join(
            f"L{n}: {line}" for n, line in enumerate(selected, start=offset)
        )
        return header + body

    def get_total_lines(self, announcement_id: str) -> int:
        """获取已缓存公告的总行数。"""
        path = self._get_cache_path(announcement_id)
        if not path.exists():
            raise FileNotFoundError(
                f"公告 {announcement_id} 未缓存，请先调用 search_announcements"
            )
        return len(path.read_text(encoding="utf-8").splitlines())
