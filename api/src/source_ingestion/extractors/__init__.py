from __future__ import annotations

from .docx import extract_docx_metadata
from .pdf import extract_pdf_metadata
from .pptx import extract_pptx_metadata
from .text import extract_text_metadata


def extract_metadata(extension: str, file_bytes: bytes) -> dict:
    extractors = {
        "pdf": extract_pdf_metadata,
        "docx": extract_docx_metadata,
        "pptx": extract_pptx_metadata,
    }
    if extension in extractors:
        return extractors[extension](file_bytes)
    if extension in {"txt", "md", "html", "htm", "epub"}:
        return extract_text_metadata(extension, file_bytes)
    raise ValueError(f"Unsupported source extension: {extension}")
