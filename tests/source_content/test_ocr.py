import io

from PIL import Image, ImageDraw, ImageFont

from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceFormat,
    SourceLocator,
)
from src.source_ingestion.extractors.docling import extract_document
from src.source_ingestion.ocr import apply_selective_ocr, route_ocr_pages
from src.source_ingestion.ocr_benchmark import compare_ocr_engines
from src.source_ingestion.rendering import RenderedArtifact


def _document(page_text: list[str]) -> ExtractedDocument:
    root = DocumentNode(
        node_id="root",
        ordinal=0,
        ordinal_path=(0,),
        kind="document",
        role="root",
        text="fixture",
        locators=[SourceLocator(page=1)],
        method=ExtractionMethod.NATIVE,
        child_ids=[f"page-{index}" for index in range(1, len(page_text) + 1)],
    )
    nodes = [root]
    for index, text in enumerate(page_text, start=1):
        nodes.append(
            DocumentNode(
                node_id=f"page-{index}",
                parent_id="root",
                ordinal=index - 1,
                ordinal_path=(0, index - 1),
                kind="text",
                role="body",
                text=text,
                locators=[SourceLocator(page=index)],
                method=ExtractionMethod.NATIVE,
            )
        )
    return ExtractedDocument(
        source_version_id="version",
        extraction_run_id="run",
        format=SourceFormat.PDF,
        page_count=len(page_text),
        nodes=nodes,
    )


def test_routing_skips_healthy_native_and_flags_sparse_corrupt_and_repeated_headers():
    document = _document(
        [
            "A healthy native page contains enough useful text to remain authoritative without OCR.",
            "Sparse",
            "Bad � � � � text with corruption that invalidates the native layer",
            "REPEATED HEADER",
            "REPEATED HEADER",
        ]
    )

    decisions = route_ocr_pages(document)

    assert [decision.selection_rule for decision in decisions] == [
        "healthy_native",
        "sparse_native",
        "corrupt_native",
        "repeated_header_only",
        "repeated_header_only",
    ]


def test_image_only_and_mixed_pdf_only_ocr_pages_without_healthy_native_text():
    image_only = extract_document(
        __import__("pathlib").Path("tests/source_content/fixtures/generated/image-only.pdf"),
        source_version_id="image-only",
        extraction_run_id="run-1",
    )
    mixed = extract_document(
        __import__("pathlib").Path("tests/source_content/fixtures/generated/mixed-native-scanned.pdf"),
        source_version_id="mixed",
        extraction_run_id="run-2",
    )

    image_result = apply_selective_ocr(image_only.document, image_only.artifacts)
    mixed_result = apply_selective_ocr(mixed.document, mixed.artifacts)

    assert image_result.document.ocr_decisions[0].should_ocr is True
    assert "SCANNED PAGE" in " ".join(node.text or "" for node in image_result.document.nodes)
    assert [decision.should_ocr for decision in mixed_result.document.ocr_decisions] == [False, True]
    assert any(node.method == ExtractionMethod.OCR and node.locators[0].page == 2 for node in mixed_result.document.nodes)


def test_rotated_sparse_page_is_read_and_records_engine_confidence():
    image = Image.new("RGB", (900, 500), "white")
    ImageDraw.Draw(image).text(
        (60, 200),
        "ROTATED REVIEW REQUIRED",
        fill="black",
        font=ImageFont.load_default(size=48),
    )
    image = image.rotate(90, expand=True)
    body = io.BytesIO()
    image.save(body, format="WEBP", lossless=True)
    document = _document(["x"])
    artifact = RenderedArtifact(
        artifact_id="page_preview-1",
        kind="page_preview",
        filename="previews/page-0001.webp",
        content_type="image/webp",
        body=body.getvalue(),
    )

    result = apply_selective_ocr(document, (artifact,))

    text = " ".join(node.text or "" for node in result.document.nodes)
    assert "ROTATED" in text and "REQUIRED" in text
    assert result.document.ocr_decisions[0].engine == "tesseract"
    assert result.document.ocr_decisions[0].confidence is not None


def test_tesseract_and_rapidocr_benchmark_selects_smallest_passing_stack():
    from pathlib import Path

    report = compare_ocr_engines(
        Path("tests/source_content/fixtures/generated/image-only.pdf"),
        ["SCANNED PAGE", "Alpha precedes Beta", "Review is required"],
    )

    assert all(engine["word_recall"] >= 0.98 for engine in report["engines"].values())
    assert report["selected_engine"] == "tesseract"
    assert report["engines"]["tesseract"]["production_incremental_dependency"] == "none"
