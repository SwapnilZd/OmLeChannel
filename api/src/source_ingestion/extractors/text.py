from __future__ import annotations
import io
import re

def extract_text_metadata(ext: str, file_bytes: bytes) -> dict:
    text = file_bytes.decode("utf-8", errors="ignore")

    if ext in ("txt", "md"):
        lines = text.splitlines()
        words = text.split()
        return {
            "word_count": len(words),
            "line_count": len(lines),
            "title": _first_heading(text) if ext == "md" else None,
        }

    elif ext in ("html", "htm"):
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', text, re.IGNORECASE)
        return {
            "title": title.group(1).strip() if title else None,
            "meta_description": desc.group(1).strip() if desc else None,
            "word_count": len(re.sub(r"<[^>]+>", " ", text).split()),
        }

    elif ext == "epub":
        try:
            import zipfile
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                # Try to read OPF for metadata
                names = z.namelist()
                opf_file = next((n for n in names if n.endswith(".opf")), None)
                if opf_file:
                    opf = z.read(opf_file).decode("utf-8", errors="ignore")
                    title = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.DOTALL)
                    author = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf, re.DOTALL)
                    chapter_count = sum(1 for n in names if n.endswith(".html") or n.endswith(".xhtml"))
                    return {
                        "title": title.group(1).strip() if title else None,
                        "author": author.group(1).strip() if author else None,
                        "chapter_count": chapter_count,
                    }
        except Exception:
            pass
        return {"title": None, "author": None, "chapter_count": None}

    return {}


def _first_heading(text: str):
    """Extract first markdown heading as title."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return None
