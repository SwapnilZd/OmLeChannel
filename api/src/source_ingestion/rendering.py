"""Local, deterministic review rendering for extracted source material."""

from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .contracts import ExtractedDocument, SourceFormat


@dataclass(frozen=True)
class RenderedArtifact:
    artifact_id: str
    kind: str
    filename: str
    content_type: str
    body: bytes


def _as_pdf(path: Path, source_format: SourceFormat, output_dir: Path) -> Path:
    if source_format == SourceFormat.PDF:
        return path
    completed = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    converted = output_dir / f"{path.stem}.pdf"
    if not converted.is_file():
        raise RuntimeError(f"LibreOffice did not produce a PDF: {completed.stderr.strip()}")
    return converted


def _webp(image) -> bytes:
    body = io.BytesIO()
    image.save(body, format="WEBP", quality=85, method=6)
    return body.getvalue()


def render_review_artifacts(path: Path, document: ExtractedDocument) -> tuple[RenderedArtifact, ...]:
    """Render one preview per extent and crops for mapped figures and tables."""
    import pypdfium2 as pdfium

    artifacts: list[RenderedArtifact] = []
    with tempfile.TemporaryDirectory(prefix="source-render-") as directory:
        pdf_path = _as_pdf(path, document.format, Path(directory))
        pdf = pdfium.PdfDocument(pdf_path)
        images = []
        page_sizes = []
        for page in pdf:
            page_sizes.append(page.get_size())
            images.append(page.render(scale=2).to_pil().convert("RGB"))
            page.close()
        if document.format == SourceFormat.PPTX:
            from pptx import Presentation

            presentation = Presentation(path)
            coordinate_width = float(presentation.slide_width)
            coordinate_height = float(presentation.slide_height)
        extent_name = "page" if document.format == SourceFormat.PDF else "slide"
        preview_kind = f"{extent_name}_preview"
        for index, image in enumerate(images, start=1):
            artifacts.append(
                RenderedArtifact(
                    artifact_id=f"{preview_kind}-{index}",
                    kind=preview_kind,
                    filename=f"previews/{extent_name}-{index:04d}.webp",
                    content_type="image/webp",
                    body=_webp(image),
                )
            )

        for node in document.nodes:
            if node.kind not in {"picture", "table"} or not node.locators:
                continue
            locator = node.locators[0]
            extent = locator.page or locator.slide
            if extent is None or extent > len(images) or locator.bbox is None:
                continue
            image = images[extent - 1]
            left, top, right, bottom = locator.bbox
            if document.format == SourceFormat.PPTX:
                crop_box = (
                    max(0, round(left / coordinate_width * image.width)),
                    max(0, round(top / coordinate_height * image.height)),
                    min(image.width, round(right / coordinate_width * image.width)),
                    min(image.height, round(bottom / coordinate_height * image.height)),
                )
            else:
                page_width, page_height = page_sizes[extent - 1]
                crop_box = (
                    max(0, round(left / page_width * image.width)),
                    max(0, round((page_height - bottom) / page_height * image.height)),
                    min(image.width, round(right / page_width * image.width)),
                    min(image.height, round((page_height - top) / page_height * image.height)),
                )
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                continue
            kind = f"{node.kind}_crop"
            artifacts.append(
                RenderedArtifact(
                    artifact_id=f"{kind}-{node.node_id}",
                    kind=kind,
                    filename=f"assets/{node.node_id}.webp",
                    content_type="image/webp",
                    body=_webp(image.crop(crop_box)),
                )
            )
        pdf.close()
    return tuple(artifacts)
