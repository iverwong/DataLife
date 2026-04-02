"""摘要数据模型验证测试。"""
import pytest
from pydantic import ValidationError

from core.data.summarizing.summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
    PeriodInfo,
)


# ── PeriodInfo ──────────────────────────────────────────
class TestPeriodInfo:
    def test_full_range(self) -> None:
        """精确日期区间：start_date + end_date + description 全部填写。"""
        p = PeriodInfo(
            start_date="2024-01-01",
            end_date="2024-12-31",
            description="2024年度",
        )
        assert p.start_date == "2024-01-01"
        assert p.end_date == "2024-12-31"
        assert p.description == "2024年度"

    def test_description_only(self) -> None:
        """仅语义描述，无精确日期。"""
        p = PeriodInfo(description="报告期末")
        assert p.start_date is None
        assert p.end_date is None
        assert p.description == "报告期末"

    def test_single_date(self) -> None:
        """时间节点场景：仅 start_date。"""
        p = PeriodInfo(start_date="2024-06-15", description="调研日")
        assert p.start_date == "2024-06-15"
        assert p.end_date is None

    def test_empty_raises(self) -> None:
        """全空 PeriodInfo 应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            PeriodInfo()  # 全空，start_date 和 description 都没有


# ── KeyDataItem ─────────────────────────────────────────
class TestKeyDataItem:
    def test_numeric_item(self) -> None:
        """标准数值型数据条目。"""
        item = KeyDataItem(
            label="营业收入",
            value=1_234_567_890.50,
            unit="元",
            period=PeriodInfo(description="2024年度"),
        )
        assert item.label == "营业收入"
        assert item.value == 1_234_567_890.50
        assert item.unit == "元"

    def test_qualitative_item(self) -> None:
        """定性描述：value 为 None。"""
        item = KeyDataItem(
            label="风险评级",
            value=None,
            remark="AA+",
        )
        assert item.value is None
        assert item.remark == "AA+"

    def test_label_required(self) -> None:
        """label 为必填字段。"""
        with pytest.raises(ValidationError):
            KeyDataItem(value=100)  # type: ignore[call-arg]


# ── ChunkSummaryOutput ──────────────────────────────────
class TestChunkSummaryOutput:
    def test_valid_output(self) -> None:
        """完整有效的摘要输出。"""
        output = ChunkSummaryOutput(
            chapter_title="第一节 重要提示",
            chapter_path=["第一节 重要提示"],
            key_points=["公司年度营收增长 15%", "净利润同比下降 3%"],
            detailed_summary="本节介绍了公司年度经营概况...",
            key_data=[
                KeyDataItem(label="营业收入", value=5e9, unit="元"),
            ],
            context_brief="第一节概述了公司年度经营情况，营收增长但净利润略有下降。",
        )
        assert output.chapter_title == "第一节 重要提示"
        assert len(output.key_points) == 2
        assert len(output.key_data) == 1

    def test_empty_label_raises(self) -> None:
        """空 label 应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            KeyDataItem(label="", value=100)

    def test_empty_key_data_allowed(self) -> None:
        """key_data 可以为空列表（某些章节无结构化数据）。"""
        output = ChunkSummaryOutput(
            chapter_title="致股东书",
            chapter_path=["致股东书"],
            key_points=["展望未来发展"],
            detailed_summary="董事长致辞内容概要...",
            key_data=[],
            context_brief="致股东书主要介绍了公司发展愿景。",
        )
        assert output.key_data == []

    def test_empty_key_points_raises(self) -> None:
        """空 key_points 应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            ChunkSummaryOutput(
                chapter_title="测试章节",
                chapter_path=["测试"],
                key_points=[],
                detailed_summary="详细摘要内容足够长",
                context_brief="上下文提示足够长",
            )

    def test_missing_required_fields(self) -> None:
        """缺少必填字段应报错。"""
        with pytest.raises(ValidationError):
            ChunkSummaryOutput(
                chapter_title="测试",
            )  # type: ignore[call-arg]


# ── ChapterSummary ──────────────────────────────────────
class TestChapterSummary:
    def test_single_chunk_chapter(self) -> None:
        """单 Chunk 章节，chunk_count=1。"""
        summary_output = ChunkSummaryOutput(
            chapter_title="第二节",
            chapter_path=["第二节"],
            key_points=["要点1"],
            detailed_summary="摘要内容足够长以满足 min_length=10",
            context_brief="上下文足够长以满足 min_length=5",
        )
        ch = ChapterSummary(
            chapter_title="第二节",
            chapter_path=["第二节"],
            summary=summary_output,
            chunk_count=1,
        )
        assert ch.chunk_count == 1


# ── DocumentSummary ─────────────────────────────────────
class TestDocumentSummary:
    def test_valid_document_summary(self) -> None:
        """完整文档摘要结构验证。"""
        summary_output = ChunkSummaryOutput(
            chapter_title="第一节",
            chapter_path=["第一节"],
            key_points=["要点1"],
            detailed_summary="摘要内容足够长以满足 min_length=10",
            context_brief="上下文足够长以满足 min_length=5",
        )
        chapter_summary = ChapterSummary(
            chapter_title="第一节",
            chapter_path=["第一节"],
            summary=summary_output,
            chunk_count=1,
        )
        doc = DocumentSummary(
            source="600000_2024-12-31",
            chapter_summaries=[chapter_summary],
            all_key_points=["全文要点1"],
            all_key_data=[],
            total_chunks_processed=10,
            total_chapters=5,
        )
        assert doc.source == "600000_2024-12-31"
        assert doc.total_chunks_processed == 10
