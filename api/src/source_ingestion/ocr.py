"""Deterministic page-level OCR routing and local Tesseract execution."""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

from .contracts import DocumentNode, ExtractedDocument, ExtractionMethod, OcrPageDecision, SourceLocator
from .hierarchy import stable_node_id, validate_document
from .rendering import RenderedArtifact


@dataclass(frozen=True)
class OcrApplication:
    document: ExtractedDocument
    warnings: tuple[str, ...]


def _native_text_by_page(document: ExtractedDocument) -> dict[int, list[str]]:
    values = {page: [] for page in range(1, (document.page_count or 0) + 1)}
    for node in document.nodes:
        if node.kind == "document" or not node.text:
            continue
        for locator in node.locators:
            if locator.page in values:
                values[locator.page].append(node.text.strip())
    return values


def route_ocr_pages(document: ExtractedDocument) -> list[OcrPageDecision]:
    pages = _native_text_by_page(document)
    normalized_counts: dict[str, int] = {}
    for texts in pages.values():
        for text in set(texts):
            normalized = " ".join(text.lower().split())
            normalized_counts[normalized] = normalized_counts.get(normalized, 0) + 1

    decisions = []
    for page, texts in pages.items():
        useful = [
            text
            for text in texts
            if not (len(text) < 100 and normalized_counts.get(" ".join(text.lower().split()), 0) > 1)
        ]
        joined = " ".join(useful)
        character_count = len(joined)
        corrupt_count = sum(ord(character) < 32 or character == "�" for character in joined)
        if texts and not useful:
            rule = "repeated_header_only"
        elif character_count == 0:
            rule = "image_only"
        elif corrupt_count / character_count > 0.05:
            rule = "corrupt_native"
        elif character_count < 40:
            rule = "sparse_native"
        else:
            rule = "healthy_native"
        decisions.append(
            OcrPageDecision(
                page=page,
                native_character_count=character_count,
                should_ocr=rule != "healthy_native",
                selection_rule=rule,
                authoritative_method=(ExtractionMethod.OCR if rule != "healthy_native" else ExtractionMethod.NATIVE),
            )
        )
    return decisions


@lru_cache(maxsize=1)
def _tesseract_version() -> str:
    output = subprocess.run(["tesseract", "--version"], check=True, capture_output=True, text=True).stdout
    return output.splitlines()[0].removeprefix("tesseract ")


def _ocr_image(body: bytes) -> tuple[str, float]:
    source = Image.open(io.BytesIO(body)).convert("RGB")
    candidates: list[tuple[float, str, float]] = []
    for angle in (0, 90, 180, 270):
        image = source.rotate(angle, expand=True)
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "11", "tsv"],
            input=encoded.getvalue(),
            check=True,
            capture_output=True,
        )
        words: list[str] = []
        confidences: list[float] = []
        for row in csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t"):
            text = (row.get("text") or "").strip()
            confidence = float(row.get("conf") or -1)
            if text and confidence >= 0:
                words.append(text)
                confidences.append(confidence)
        joined = " ".join(words)
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        candidates.append((len(joined) * mean_confidence, joined, mean_confidence / 100))
    _, text, confidence = max(candidates, key=lambda value: value[0])
    return text, confidence


def extract_visible_text(body: bytes) -> tuple[str, float]:
    """Extract crop text used to ground a visual explanation."""
    return _ocr_image(body)


def apply_selective_ocr(
    document: ExtractedDocument,
    artifacts: tuple[RenderedArtifact, ...],
) -> OcrApplication:
    if document.page_count is None:
        return OcrApplication(document=document, warnings=())
    previews = {
        int(artifact.artifact_id.rsplit("-", 1)[-1]): artifact.body
        for artifact in artifacts
        if artifact.kind == "page_preview"
    }
    nodes = list(document.nodes)
    root = nodes[0]
    child_ids = list(root.child_ids)
    warnings: list[str] = []
    completed: list[OcrPageDecision] = []
    for decision in route_ocr_pages(document):
        if not decision.should_ocr:
            completed.append(decision)
            continue
        body = previews.get(decision.page)
        if body is None:
            warnings.append(f"ocr_preview_missing:{decision.page}")
            completed.append(decision.model_copy(update={"authoritative_method": ExtractionMethod.UNKNOWN}))
            continue
        text, confidence = _ocr_image(body)
        ordinal = len(child_ids)
        node_id = stable_node_id(document.source_version_id, kind="ocr_page", ordinal_path=(0, ordinal))
        if text:
            nodes.append(
                DocumentNode(
                    node_id=node_id,
                    parent_id=root.node_id,
                    ordinal=ordinal,
                    ordinal_path=(0, ordinal),
                    kind="ocr_text",
                    role="page_text",
                    text=text,
                    locators=[SourceLocator(page=decision.page)],
                    method=ExtractionMethod.OCR,
                    confidence=confidence,
                )
            )
            child_ids.append(node_id)
        if confidence < 0.65:
            warnings.append(f"ocr_low_confidence:{decision.page}")
        completed.append(
            decision.model_copy(
                update={
                    "engine": "tesseract",
                    "engine_version": _tesseract_version(),
                    "confidence": confidence,
                    "authoritative_method": ExtractionMethod.OCR if text else ExtractionMethod.UNKNOWN,
                }
            )
        )
    nodes[0] = root.model_copy(update={"child_ids": child_ids})
    updated = document.model_copy(update={"nodes": nodes, "ocr_decisions": completed})
    return OcrApplication(document=validate_document(updated), warnings=tuple(warnings))
