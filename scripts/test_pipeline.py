"""CLI 验证管线工具。

提供命令行工具，输入 PDF 路径和输出目录，运行 Step 1（PDF 解析）+ Step 2（逻辑分块）管线，
将各阶段产物导出为人类可读文件，便于人工校验。

Usage:
    python -m scripts.test_pipeline --pdf <PDF路径> --output <输出目录>
"""

import argparse
import asyncio
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import logfire

from core.data.chunk_pipeline import chunk_document
from core.data.models import ChunkList, PDFParseResult
from core.data.pdf_parser import parse_pdf


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="CLI 验证管线工具 - PDF解析+逻辑分块导出"
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="PDF 文件路径",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出目录路径（不存在时自动创建）",
    )
    parser.add_argument(
        "--stock-code",
        default=None,
        help="股票代码，默认从文件名推断或 'unknown'",
    )
    parser.add_argument(
        "--report-date",
        default=None,
        help="报告日期，默认从文件名推断或 'unknown'",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=300000,
        help="单 Chunk 最大 token 数，默认 300000（300K）",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=1000,
        help="相邻 Chunk 重叠 token 数，默认 1000（1K）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def infer_metadata(pdf_path: str) -> tuple[str, str]:
    """从文件名推断股票代码和报告日期。

    Args:
        pdf_path: PDF 文件路径

    Returns:
        tuple[stock_code, report_date]
    """
    filename = Path(pdf_path).stem

    # 股票代码正则：匹配第一个连续6位数字
    stock_match = re.search(r"(\d{6})", filename)
    stock_code = stock_match.group(1) if stock_match else "unknown"

    # 报告日期正则：匹配4位年份 + 可选后缀
    date_match = re.search(r"(\d{4})[年\-_]?[度]?(?:年度|年|半年度|季度)?", filename)
    report_date = date_match.group(1) if date_match else "unknown"

    return stock_code, report_date


def sanitize_filename(name: str) -> str:
    """对章节名做文件名安全处理。

    - 替换 [\\/:*?"<>|] 为下划线
    - 截断到40字符
    - 空字符串返回 "unnamed"

    Args:
        name: 原始章节名

    Returns:
        处理后的安全文件名
    """
    if not name:
        return "unnamed"

    # 替换非法字符
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)

    # 截断到40字符
    if len(safe) > 40:
        safe = safe[:40]

    return safe


def run_step1(
    pdf_path: str,
    output_dir: Path,
) -> PDFParseResult:
    """执行 Step 1：PDF 解析。

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录

    Returns:
        PDFParseResult 解析结果
    """
    step1_dir = output_dir / "step1_parse"
    pages_dir = step1_dir / "pages"

    # 创建目录
    step1_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    # 执行解析
    print(f"[Step 1] 开始解析 PDF: {pdf_path}")
    result: PDFParseResult = asyncio.run(parse_pdf(pdf_path))
    print(f"[Step 1] 解析完成，共 {result.page_count} 页")

    # 导出 full_text.md
    full_text_path = step1_dir / "full_text.md"
    full_text_path.write_text(result.full_text, encoding="utf-8")
    print(f"[Step 1] 已导出: {full_text_path.name}")

    # 导出 metadata.json
    metadata = {
        "source": result.source,
        "page_count": result.page_count,
    }
    metadata_path = step1_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Step 1] 已导出: {metadata_path.name}")

    # 导出 toc.json（汇总所有页面的 toc_items）
    toc_items = []
    for chunk in result.chunks:
        toc_items.extend(chunk.toc_items)

    toc_path = step1_dir / "toc.json"
    toc_path.write_text(
        json.dumps(toc_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Step 1] 已导出: {toc_path.name} ({len(toc_items)} 项)")

    # 导出逐页 markdown
    for i, chunk in enumerate(result.chunks):
        page_num = chunk.page_number
        page_path = pages_dir / f"page_{page_num:03d}.md"
        page_path.write_text(chunk.markdown_text, encoding="utf-8")

    print(f"[Step 1] 已导出: {pages_dir.name}/ ({result.page_count} 页)")

    return result


def run_step2(
    content: bytes,
    parsed: PDFParseResult,
    output_dir: Path,
    max_tokens: int,
    overlap_tokens: int,
    stock_code: str,
    report_date: str,
) -> ChunkList:
    """执行 Step 2：逻辑分块。

    Args:
        content: PDF 原始字节
        parsed: Step 1 解析结果
        output_dir: 输出目录
        max_tokens: 单 Chunk 最大 token 数
        overlap_tokens: 相邻 Chunk 重叠 token 数
        stock_code: 股票代码
        report_date: 报告日期

    Returns:
        ChunkList 分块结果
    """
    step2_dir = output_dir / "step2_chunk"
    chunks_dir = step2_dir / "chunks"

    # 创建目录
    step2_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # 执行分块
    print(f"[Step 2] 开始逻辑分块 (max_tokens={max_tokens}, overlap={overlap_tokens})")
    chunk_list: ChunkList = asyncio.run(
        chunk_document(
            content,
            parsed,
            stock_code=stock_code,
            report_date=report_date,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            persist=False,
        )
    )
    print(f"[Step 2] 分块完成，共 {len(chunk_list.chunks)} 个 chunks")

    # 导出 chunk_list.json（排除 text 字段避免过大）
    chunk_list_data: list[dict[str, Any]] = []
    for chunk in chunk_list.chunks:
        d: dict[str, Any] = {
            "chapter_path": chunk.chapter_path,
            "page_range": list(chunk.page_range),
            "token_count": chunk.token_count,
            "chunk_type": chunk.chunk_type.value,
            "needs_prior_summary": chunk.needs_prior_summary,
            "chunk_index": chunk.chunk_index,
            "contained_chapters": [
                {
                    "title": c.title,
                    "level": c.level,
                    "page_range": list(c.page_range),
                }
                for c in chunk.contained_chapters
            ],
        }
        chunk_list_data.append(d)

    chunk_list_path = step2_dir / "chunk_list.json"
    chunk_list_path.write_text(
        json.dumps(chunk_list_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Step 2] 已导出: {chunk_list_path.name}")

    # 导出 stats.json
    stats = {
        "total_tokens": chunk_list.total_tokens,
        "chunk_count": len(chunk_list.chunks),
        "chapter_count": chunk_list.chapter_count,
        "source": chunk_list.source,
    }
    stats_path = step2_dir / "stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Step 2] 已导出: {stats_path.name}")

    # 导出 summary_table.md
    table_lines = [
        "| # | 章节 | 页码 | Token | 类型 | 包含章节数 |",
        "|---|------|------|-------|------|------------|",
    ]
    for i, chunk in enumerate(chunk_list.chunks):
        chapter = chunk.chapter_path[-1] if chunk.chapter_path else "ROOT"
        page_range = f"{chunk.page_range[0]}-{chunk.page_range[1]}"
        chunk_type = chunk.chunk_type.value
        contained_count = len(chunk.contained_chapters)
        table_lines.append(
            f"| {i} | {chapter} | {page_range} | {chunk.token_count} | {chunk_type} | {contained_count} |"
        )

    summary_path = step2_dir / "summary_table.md"
    summary_path.write_text("\n".join(table_lines), encoding="utf-8")
    print(f"[Step 2] 已导出: {summary_path.name}")

    # 导出逐块 markdown
    for i, chunk in enumerate(chunk_list.chunks):
        chapter_name = chunk.chapter_path[-1] if chunk.chapter_path else "root"
        safe_name = sanitize_filename(chapter_name)
        chunk_filename = f"chunk_{i:03d}_{safe_name}.md"

        # 构建头部元信息
        header = f"""\
<!--
chunk_index: {i}
chapter_path: {" > ".join(chunk.chapter_path)}
page_range: {chunk.page_range[0]}-{chunk.page_range[1]}
token_count: {chunk.token_count}
chunk_type: {chunk.chunk_type.value}
-->
"""
        chunk_content = header + chunk.text

        chunk_path = chunks_dir / chunk_filename
        chunk_path.write_text(chunk_content, encoding="utf-8")

    print(f"[Step 2] 已导出: {chunks_dir.name}/ ({len(chunk_list.chunks)} 个 chunks)")

    return chunk_list


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    """主管线编排。

    Args:
        args: 解析后的命令行参数

    Returns:
        汇总结果字典
    """
    pdf_path = args.pdf
    output_dir = Path(args.output)

    # 推断元数据
    inferred_stock, inferred_date = infer_metadata(pdf_path)
    stock_code = args.stock_code or inferred_stock
    report_date = args.report_date or inferred_date

    print("\n" + "=" * 60)
    print("CLI 验证管线工具")
    print("=" * 60)
    print(f"PDF: {pdf_path}")
    print(f"输出目录: {output_dir}")
    print(f"股票代码: {stock_code}")
    print(f"报告日期: {report_date}")
    print(f"Max Tokens: {args.max_tokens}")
    print(f"Overlap: {args.overlap}")
    print(f"{'='*60}\n")

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 记录开始时间
    start_time = time.time()

    result: dict[str, Any] = {
        "pdf": pdf_path,
        "output": str(output_dir),
        "stock_code": stock_code,
        "report_date": report_date,
        "step1_success": False,
        "step2_success": False,
        "error": None,
    }

    # Step 1: PDF 解析
    parsed_result: PDFParseResult | None = None
    step1_start = 0.0
    step1_elapsed = 0.0
    try:
        step1_start = time.time()
        parsed_result = run_step1(pdf_path, output_dir)
        step1_elapsed = time.time() - step1_start
        result["step1_success"] = True
        result["step1_elapsed"] = round(step1_elapsed, 2)
        print(f"[Step 1] 完成，耗时 {step1_elapsed:.2f}s\n")
    except Exception as e:
        if step1_start > 0:
            step1_elapsed = time.time() - step1_start
        result["step1_elapsed"] = round(step1_elapsed, 2)
        result["error"] = str(e)
        print(f"[Step 1] 失败: {e}")
        traceback.print_exc()
        print("\n[Step 1] 失败，跳过 Step 2")
        result["total_elapsed"] = round(time.time() - start_time, 2)
        return result

    # Step 2: 逻辑分块
    step2_start = 0.0
    step2_elapsed = 0.0
    if parsed_result:
        try:
            step2_start = time.time()

            # 读取 PDF 原始字节
            content = Path(pdf_path).read_bytes()

            run_step2(
                content,
                parsed_result,
                output_dir,
                args.max_tokens,
                args.overlap,
                stock_code,
                report_date,
            )
            step2_elapsed = time.time() - step2_start
            result["step2_success"] = True
            result["step2_elapsed"] = round(step2_elapsed, 2)
            print(f"[Step 2] 完成，耗时 {step2_elapsed:.2f}s\n")
        except Exception as e:
            if step2_start > 0:
                step2_elapsed = time.time() - step2_start
            result["step2_elapsed"] = round(step2_elapsed, 2)
            result["error"] = str(e)
            print(f"[Step 2] 失败: {e}")
            traceback.print_exc()

    # 汇总
    total_elapsed = time.time() - start_time
    result["total_elapsed"] = round(total_elapsed, 2)

    print(f"{'='*60}")
    print("执行汇总")
    print(f"{'='*60}")
    print(f"Step 1 (PDF 解析): {'✓ 成功' if result['step1_success'] else '✗ 失败'} ({result.get('step1_elapsed', 0)}s)")
    print(f"Step 2 (逻辑分块): {'✓ 成功' if result['step2_success'] else '✗ 失败'} ({result.get('step2_elapsed', 0)}s)")
    print(f"总耗时: {total_elapsed:.2f}s")

    if result["error"]:
        print(f"错误: {result['error']}")

    return result


def main() -> None:
    """CLI 入口函数。"""
    args = parse_args()

    # 配置日志（仅输出到控制台）
    logfire.configure(
        send_to_logfire=False,  # 禁用 logfire 发送，仅输出到控制台
    )

    result = run_pipeline(args)

    # 退出码
    if result["error"] and not (result["step1_success"] and result["step2_success"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
