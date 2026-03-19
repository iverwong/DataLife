"""Parsing submodule - PDF parsing and splitting utilities."""

from .pdf_parser import (
    DEFAULT_OCR_LANGUAGE,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFFileNotFoundError,
    PDFParsingError,
    parse_pdf,
    parse_pdf_bytes,
)
from .pdf_split import CHUNK_SIZE, REP_SIZE, split_pdf

__all__ = [
    # pdf_parser
    "parse_pdf",
    "parse_pdf_bytes",
    "PDFParsingError",
    "PDFFileNotFoundError",
    "PDFEncryptedError",
    "PDFCorruptedError",
    "DEFAULT_OCR_LANGUAGE",
    # pdf_split
    "split_pdf",
    "CHUNK_SIZE",
    "REP_SIZE",
]
