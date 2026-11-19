from __future__ import annotations
import io
from typing import Optional

def extract_pdf_metadata(file_bytes: bytes) -> dict:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
            meta = pdf.metadata or {}
            return {
                "page_count": page_count,
                "title": meta.get("Title") or None,
                "author": meta.get("Author") or None,
            }
    except ImportError:
        # pdfplumber not installed — return basic info
        return {"page_count": None, "title": None, "author": None}
