"""Pinned Docling adapter producing the canonical extraction contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    NodeRelationship,
    RelationshipType,
    SourceFormat,
    SourceLocator,
    SourceSegment,
)
from ..hierarchy import stable_node_id, validate_document
from ..rendering import RenderedArtifact, render_review_artifacts
from ..segmentation import DEFAULT_SEGMENT_TOKENS, build_source_segment


@dataclass(frozen=True)
class DoclingExtraction:
    document: ExtractedDocument
    original: dict[str, Any]
    warnings: tuple[str, ...]
    artifacts: tuple[RenderedArtifact, ...]
    segments: tuple[SourceSegment, ...]


def _converter_for(source_format: SourceFormat):
    from docling.document_converter import DocumentConverter, PdfFormatOption

    if source_format == SourceFormat.PPTX:
        return DocumentConverter()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.object_detection_engine_options import (
        TransformersObjectDetectionEngineOptions,
    )
    from docling.datamodel.pipeline_options import (
        LayoutObjectDetectionOptions,
        PdfPipelineOptions,
    )

    options = PdfPipelineOptions(
        artifacts_path=Path("/opt/docling-models"),
        do_ocr=False,
        do_table_structure=True,
        enable_remote_services=False,
        allow_external_plugins=False,
        layout_options=LayoutObjectDetectionOptions(
            engine_options=TransformersObjectDetectionEngineOptions(
                compile_model=False,
            )
        ),
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def _bbox(provenance) -> tuple[float, float, float, float] | None:
    bbox = getattr(provenance, "bbox", None)
    if bbox is None:
        return None
    values = (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
    left, top, right, bottom = values
    return (min(left, right), min(top, bottom), max(left, right), max(top, bottom))


def _item_text(item, docling_document) -> str | None:
    text = getattr(item, "text", None)
    if text:
        return text.strip()
    if type(item).__name__ == "TableItem":
        markdown = item.export_to_markdown(doc=docling_document)
        return markdown.strip() or None
    return None


def extract_document(
    path: Path,
    *,
    source_version_id: str,
    extraction_run_id: str,
) -> DoclingExtraction:
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".pptx"}:
        raise ValueError(f"unsupported extraction format: {suffix}")
    source_format = SourceFormat.PDF if suffix == ".pdf" else SourceFormat.PPTX
    result = _converter_for(source_format).convert(path)
    docling_document = result.document
    original = docling_document.export_to_dict()
    page_count = len(docling_document.pages)
    extent_name = "page" if source_format == SourceFormat.PDF else "slide"
    root_id = stable_node_id(source_version_id, kind="document", ordinal_path=(0,))
    child_nodes: list[DocumentNode] = []
    warnings: list[str] = []

    for ordinal, (item, _level) in enumerate(docling_document.iterate_items()):
        provenance = next(iter(getattr(item, "prov", [])), None)
        position = int(getattr(provenance, "page_no", 1))
        label = str(getattr(item, "label", "unknown")).split(".")[-1]
        text = _item_text(item, docling_document)
        asset_id = None
        if type(item).__name__ == "PictureItem":
            asset_id = f"asset-{ordinal}"
        if text is None and asset_id is None:
            label = "unknown"
            text = f"Preserved Docling item {getattr(item, 'self_ref', ordinal)}"
            warnings.append(f"unmapped_item:{ordinal}")
        path_value = (0, ordinal)
        locator_values = {extent_name: position, "bbox": _bbox(provenance)}
        child_nodes.append(
            DocumentNode(
                node_id=stable_node_id(
                    source_version_id,
                    kind=label,
                    ordinal_path=path_value,
                ),
                parent_id=root_id,
                ordinal=ordinal,
                ordinal_path=path_value,
                kind=label,
                role=label,
                native_ref=str(getattr(item, "self_ref", "")) or None,
                text=text,
                asset_id=asset_id,
                locators=[SourceLocator(**locator_values)],
                method=ExtractionMethod.NATIVE,
                confidence=getattr(provenance, "score", None),
            )
        )

    relationships: list[NodeRelationship] = []
    if source_format == SourceFormat.PPTX:
        child_nodes, note_relationships = _supplement_pptx_notes(
            path, source_version_id, root_id, child_nodes
        )
        relationships.extend(note_relationships)

    root = DocumentNode(
        node_id=root_id,
        ordinal=0,
        ordinal_path=(0,),
        kind="document",
        role="root",
        text=docling_document.name or path.stem,
        locators=[SourceLocator(**{extent_name: 1})],
        method=ExtractionMethod.NATIVE,
        child_ids=[node.node_id for node in child_nodes],
    )
    document = ExtractedDocument(
        source_version_id=source_version_id,
        extraction_run_id=extraction_run_id,
        format=source_format,
        page_count=page_count if source_format == SourceFormat.PDF else None,
        slide_count=page_count if source_format == SourceFormat.PPTX else None,
        nodes=[root, *child_nodes],
        relationships=relationships,
    )
    validated = validate_document(document)
    segments = _docling_segments(docling_document, validated)
    return DoclingExtraction(
        document=validated,
        original=original,
        warnings=tuple(warnings),
        artifacts=render_review_artifacts(path, validated),
        segments=segments,
    )


def _docling_segments(
    docling_document, document: ExtractedDocument
) -> tuple[SourceSegment, ...]:
    import tiktoken
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

    encoding = tiktoken.get_encoding("o200k_base")
    chunker = HybridChunker(
        tokenizer=OpenAITokenizer(
            tokenizer=encoding,
            max_tokens=DEFAULT_SEGMENT_TOKENS,
        ),
        repeat_table_header=True,
        omit_header_on_overflow=True,
    )
    nodes_by_ref = {
        node.native_ref: node for node in document.nodes if node.native_ref is not None
    }
    chunks = list(chunker.chunk(dl_doc=docling_document))
    reference_counts: dict[str, int] = {}
    for chunk in chunks:
        for item in chunk.meta.doc_items:
            reference = str(item.self_ref)
            reference_counts[reference] = reference_counts.get(reference, 0) + 1

    segments = []
    for chunk in chunks:
        references = list(
            dict.fromkeys(str(item.self_ref) for item in chunk.meta.doc_items)
        )
        nodes = [
            nodes_by_ref[reference]
            for reference in references
            if reference in nodes_by_ref
        ]
        text = chunker.contextualize(chunk).strip()
        if not nodes or not text:
            continue
        segments.append(
            build_source_segment(
                document,
                nodes,
                text,
                ordinal=len(segments),
                encoding=encoding,
                split_from_node=any(
                    reference_counts[reference] > 1 for reference in references
                ),
            )
        )
    return tuple(segments)


def _supplement_pptx_notes(
    path: Path,
    source_version_id: str,
    root_id: str,
    nodes: list[DocumentNode],
) -> tuple[list[DocumentNode], list[NodeRelationship]]:
    from pptx import Presentation
    from pptx.enum.shapes import PP_PLACEHOLDER

    relationships: list[NodeRelationship] = []
    for slide_number, slide in enumerate(Presentation(path).slides, start=1):
        note_text = ""
        for placeholder in slide.notes_slide.placeholders:
            if placeholder.placeholder_format.type == PP_PLACEHOLDER.BODY:
                note_text = placeholder.text.strip()
                break
        if not note_text:
            continue
        ordinal = len(nodes)
        note_id = stable_node_id(
            source_version_id,
            kind="speaker_note",
            ordinal_path=(0, ordinal),
        )
        nodes.append(
            DocumentNode(
                node_id=note_id,
                parent_id=root_id,
                ordinal=ordinal,
                ordinal_path=(0, ordinal),
                kind="speaker_note",
                role="speaker_note",
                text=note_text,
                locators=[SourceLocator(slide=slide_number)],
                method=ExtractionMethod.NATIVE,
            )
        )
        slide_nodes = [
            node for node in nodes[:-1] if node.locators[0].slide == slide_number
        ]
        if slide_nodes:
            relationships.append(
                NodeRelationship(
                    relationship_id=f"speaker-note-{slide_number}",
                    type=RelationshipType.SPEAKER_NOTE_OF,
                    source_node_id=note_id,
                    target_node_id=slide_nodes[0].node_id,
                )
            )
    return nodes, relationships
