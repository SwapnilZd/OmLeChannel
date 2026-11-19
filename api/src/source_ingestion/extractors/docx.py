from __future__ import annotations
import io

def extract_docx_metadata(file_bytes: bytes) -> dict:
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        word_count = sum(
            len(para.text.split())
            for para in doc.paragraphs
            if para.text.strip()
        )
        props = doc.core_properties
        return {
            "word_count": word_count,
            "title": props.title or None,
            "author": props.author or None,
        }
    except ImportError:
        return {"word_count": None, "title": None, "author": None}
