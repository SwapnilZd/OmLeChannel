"""Validate and score the source-extraction benchmark corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import resource
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BenchmarkThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_coverage: float = Field(ge=0, le=1)
    reading_order: float = Field(ge=0, le=1)
    hierarchy_accuracy: float = Field(ge=0, le=1)
    table_fidelity: float = Field(ge=0, le=1)
    notes_coverage: float = Field(ge=0, le=1)
    visual_coverage: float = Field(ge=0, le=1)
    locator_accuracy: float = Field(ge=0, le=1)


class BenchmarkExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_pages: int | None = Field(default=None, ge=1)
    minimum_slides: int | None = Field(default=None, ge=1)
    feature_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_format_extent(self) -> "BenchmarkExpectations":
        if self.minimum_pages is None and self.minimum_slides is None:
            raise ValueError("a benchmark case must declare pages or slides")
        return self


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    format: str
    provenance: str
    sha256: str | None = None
    generated: bool = False
    gold_path: str | None = None
    expectations: BenchmarkExpectations


class GoldLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    page: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_single_extent(self) -> "GoldLocator":
        if (self.page is None) == (self.slide is None):
            raise ValueError("a gold locator must declare exactly one page or slide")
        return self


class GoldAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    case_id: str
    ordered_text: list[str] = Field(min_length=1)
    hierarchy: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    visuals: list[dict[str, Any]] = Field(default_factory=list)
    locators: list[GoldLocator] = Field(min_length=1)


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    thresholds: BenchmarkThresholds
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "BenchmarkManifest":
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark case IDs must be unique")
        return self


def load_manifest(path: Path) -> BenchmarkManifest:
    return BenchmarkManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_gold_annotation(path: Path) -> GoldAnnotation:
    return GoldAnnotation.model_validate_json(path.read_text(encoding="utf-8"))


def validate_corpus(manifest_path: Path, repository_root: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    cases: list[dict[str, Any]] = []
    for case in manifest.cases:
        source_path = repository_root / case.path
        exists = source_path.is_file()
        gold_exists = case.gold_path is None
        if case.gold_path:
            gold_path = repository_root / case.gold_path
            gold_exists = gold_path.is_file()
            if gold_exists:
                gold = load_gold_annotation(gold_path)
                gold_exists = gold.case_id == case.id
        checksum_matches: bool | None = None
        if exists and case.sha256:
            checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
            checksum_matches = checksum == case.sha256
        cases.append(
            {
                "id": case.id,
                "path": case.path,
                "exists": exists,
                "gold_exists": gold_exists,
                "checksum_matches": checksum_matches,
                "feature_tags": case.expectations.feature_tags,
            }
        )
    return {
        "schema_version": manifest.schema_version,
        "case_count": len(cases),
        "ready": all(
            item["exists"]
            and item["gold_exists"]
            and item["checksum_matches"] is not False
            for item in cases
        ),
        "cases": cases,
    }


def _contains_score(expected: list[str], actual: str) -> float:
    if not expected:
        return 1.0
    def normalize(value: str) -> str:
        value = re.sub(r"\[\d+\]\s*", "", value)
        return " ".join(value.lower().split())

    normalized = normalize(actual)
    return sum(normalize(value) in normalized for value in expected) / len(expected)


def _score_case(case: BenchmarkCase, gold: GoldAnnotation, extraction) -> dict[str, float]:
    from .quality import evaluate_extraction

    document = extraction.document
    node_text = [node.text or "" for node in document.nodes if node.kind != "document"]
    combined_text = "\n".join(node_text)
    expected_positions = [combined_text.find(value) for value in gold.ordered_text]
    present_positions = [position for position in expected_positions if position >= 0]
    reading_order = (
        sum(left < right for left, right in zip(present_positions, present_positions[1:]))
        / (len(present_positions) - 1)
        if len(present_positions) > 1
        else float(bool(present_positions))
    )
    table_text = "\n".join(node.text or "" for node in document.nodes if node.kind == "table")
    expected_table_values = [
        str(value)
        for table in gold.tables
        for value in [*table.get("headers", []), *[cell for row in table.get("rows", []) for cell in row]]
    ]
    expected_visual_extents = {
        locator.page or locator.slide
        for locator in gold.locators
        if any(visual.get("node_id") == locator.node_id for visual in gold.visuals)
    }
    captured_visual_extents = {
        node.locators[0].page or node.locators[0].slide
        for node in document.nodes
        if node.asset_id and any(node.node_id in artifact.artifact_id for artifact in extraction.artifacts)
    }
    expected_locator_extents = {locator.page or locator.slide for locator in gold.locators}
    actual_locator_extents = {
        locator.page or locator.slide
        for node in document.nodes
        if node.kind != "document"
        for locator in node.locators
    }
    deterministic = evaluate_extraction(
        document,
        mapping_warnings=extraction.warnings,
        artifact_ids={artifact.artifact_id for artifact in extraction.artifacts},
    )
    return {
        "text_coverage": _contains_score(gold.ordered_text, combined_text),
        "reading_order": reading_order,
        "hierarchy_accuracy": deterministic.hierarchy_accuracy,
        "table_fidelity": _contains_score(expected_table_values, table_text),
        "notes_coverage": _contains_score(gold.notes, combined_text),
        "visual_coverage": (
            len(expected_visual_extents & captured_visual_extents) / len(expected_visual_extents)
            if expected_visual_extents
            else 1.0
        ),
        "locator_accuracy": len(expected_locator_extents & actual_locator_extents) / len(expected_locator_extents),
    }


def run_extraction_benchmark(manifest_path: Path, repository_root: Path) -> dict[str, Any]:
    from .extractors.docling import extract_document

    manifest = load_manifest(manifest_path)
    results: list[dict[str, Any]] = []
    for case in manifest.cases:
        if not case.gold_path or "image_only" in case.expectations.feature_tags:
            continue
        usage_before = resource.getrusage(resource.RUSAGE_SELF)
        started = time.perf_counter()
        extraction = extract_document(
            repository_root / case.path,
            source_version_id=f"benchmark-{case.id}",
            extraction_run_id="benchmark-run",
        )
        elapsed = time.perf_counter() - started
        usage_after = resource.getrusage(resource.RUSAGE_SELF)
        gold = load_gold_annotation(repository_root / case.gold_path)
        results.append(
            {
                "id": case.id,
                "metrics": _score_case(case, gold, extraction),
                "elapsed_seconds": round(elapsed, 3),
                "cpu_seconds": round(
                    (usage_after.ru_utime + usage_after.ru_stime)
                    - (usage_before.ru_utime + usage_before.ru_stime),
                    3,
                ),
                "gpu_used": False,
                "preview_asset_bytes": sum(len(artifact.body) for artifact in extraction.artifacts),
                "artifact_count": len(extraction.artifacts),
                "node_count": len(extraction.document.nodes),
                "warning_count": len(extraction.warnings),
            }
        )
    aggregate = {
        metric: sum(result["metrics"][metric] for result in results) / len(results)
        for metric in BenchmarkThresholds.model_fields
    }
    thresholds = manifest.thresholds.model_dump()
    return {
        "schema_version": "source-extraction-benchmark-result-v1",
        "passed": all(aggregate[name] >= threshold for name, threshold in thresholds.items()),
        "aggregate": aggregate,
        "thresholds": thresholds,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    report = validate_corpus(args.manifest, args.repository_root)
    if report["ready"] and not args.validate_only:
        report = run_extraction_benchmark(args.manifest, args.repository_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report.get("ready", report.get("passed", False)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
