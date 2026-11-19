"""Deterministic extraction-quality scores and warnings."""

from __future__ import annotations

from .contracts import ExtractedDocument, ExtractionQualityReport, ExtractionWarning


def evaluate_extraction(
    document: ExtractedDocument,
    *,
    mapping_warnings: tuple[str, ...] = (),
    artifact_ids: set[str] | None = None,
) -> ExtractionQualityReport:
    content_nodes = [node for node in document.nodes if node.kind != "document"]
    extent_count = (
        document.page_count or document.slide_count or document.chapter_count or 1
    )
    extent_name = (
        "page" if document.page_count else "slide" if document.slide_count else "chapter"
    )
    warnings: list[ExtractionWarning] = []
    text_by_extent = {index: 0 for index in range(1, extent_count + 1)}
    valid_locators = 0
    for node in content_nodes:
        for locator in node.locators:
            extent = locator.page or locator.slide or locator.chapter
            if extent is not None and extent <= extent_count:
                valid_locators += 1
                if node.text:
                    text_by_extent[extent] += len(node.text.strip())

    for extent, character_count in text_by_extent.items():
        if character_count == 0:
            warnings.append(ExtractionWarning(code="missing_extent", message=f"No mapped text was found on {extent_name} {extent}."))
        if character_count < 20:
            warnings.append(ExtractionWarning(code="sparse_extent", message=f"{extent_name.title()} {extent} has sparse extracted text.", severity="info"))
    for node in content_nodes:
        if node.kind == "unknown":
            warnings.append(ExtractionWarning(code="unsupported_object", message="An extractor object could not be mapped to a canonical role.", node_id=node.node_id))
    warnings.extend(ExtractionWarning(code="mapping_loss", message=value) for value in mapping_warnings)
    required_ocr = [decision for decision in document.ocr_decisions if decision.should_ocr]
    completed_ocr = [
        decision
        for decision in required_ocr
        if decision.authoritative_method.value == "ocr" and decision.confidence is not None
    ]
    for decision in required_ocr:
        if decision.authoritative_method.value == "unknown":
            warnings.append(ExtractionWarning(code="ocr_missing", message=f"OCR produced no usable text for page {decision.page}."))
        elif decision.confidence is not None and decision.confidence < 0.65:
            warnings.append(ExtractionWarning(code="ocr_low_confidence", message=f"OCR confidence is low for page {decision.page}."))

    ordinal_paths = [node.ordinal_path for node in content_nodes]
    ordered = len(ordinal_paths) == len(set(ordinal_paths)) and ordinal_paths == sorted(ordinal_paths)
    if not ordered:
        warnings.append(ExtractionWarning(code="ambiguous_order", message="Canonical ordinal paths are duplicated or out of order."))

    node_ids = {node.node_id for node in document.nodes}
    hierarchy_total = sum(node.parent_id is not None for node in content_nodes)
    hierarchy_valid = sum(node.parent_id in node_ids for node in content_nodes if node.parent_id is not None)
    tables = [node for node in content_nodes if node.kind == "table"]
    notes = [node for node in content_nodes if node.kind == "speaker_note"]
    visuals = [node for node in content_nodes if node.asset_id]
    available_artifacts = artifact_ids or set()
    captured_visuals = sum(any(node.node_id in artifact_id for artifact_id in available_artifacts) for node in visuals)
    locator_total = sum(len(node.locators) for node in content_nodes)

    return ExtractionQualityReport(
        text_coverage=sum(count > 0 for count in text_by_extent.values()) / extent_count,
        reading_order=1.0 if ordered else 0.0,
        hierarchy_accuracy=hierarchy_valid / hierarchy_total if hierarchy_total else 1.0,
        table_fidelity=sum(bool(node.text) for node in tables) / len(tables) if tables else 1.0,
        notes_coverage=len({node.locators[0].slide for node in notes}) / extent_count if document.slide_count else 1.0,
        visual_coverage=captured_visuals / len(visuals) if visuals else 1.0,
        locator_accuracy=valid_locators / locator_total if locator_total else 1.0,
        ocr_coverage=len(completed_ocr) / len(required_ocr) if required_ocr else 1.0,
        warnings=warnings,
    )
