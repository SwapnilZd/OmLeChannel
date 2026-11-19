from __future__ import annotations
import io

def extract_pptx_metadata(file_bytes: bytes) -> dict:
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(file_bytes))
        slide_count = len(prs.slides)
        props = prs.core_properties
        return {
            "slide_count": slide_count,
            "title": props.title or None,
            "author": props.author or None,
        }
    except ImportError:
        return {"slide_count": None, "title": None, "author": None}
