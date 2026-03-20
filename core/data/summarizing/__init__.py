"""Summarizing submodule - summary generation pipeline.

Re-exports for convenient access:
- Models: PeriodInfo, KeyDataItem, ChunkSummaryOutput, ChapterSummary, DocumentSummary
- Utils: SummarizeContext, build_summarize_context, summarize_chunk (from chunk_summarizer)
- Merger: build_single_chunk_chapter, merge_chapter_summaries (from chapter_merger)

Note: Pipeline and storage re-exports omitted to avoid circular imports with core.db.models.
Direct imports remain available:
- from core.data.summarizing.summary_pipeline import summarize_document
- from core.data.summarizing.summary_storage import save_*
"""
from .chapter_merger import build_single_chunk_chapter, merge_chapter_summaries
from .chunk_summarizer import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    build_summarize_context,
    summarize_chunk,
)
from .summary_models import (
    ChapterSummary,
    ChunkSummaryOutput,
    DocumentSummary,
    KeyDataItem,
    PeriodInfo,
    SummarizeContext,
)

__all__ = [
    # Models
    "PeriodInfo",
    "KeyDataItem",
    "ChunkSummaryOutput",
    "ChapterSummary",
    "DocumentSummary",
    # Utils
    "SummarizeContext",
    "build_summarize_context",
    "summarize_chunk",
    "DEFAULT_MODEL",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MAX_RETRIES",
    # Merger
    "build_single_chunk_chapter",
    "merge_chapter_summaries",
]
