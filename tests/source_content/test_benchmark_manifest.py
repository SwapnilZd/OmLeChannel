from pathlib import Path

from src.source_ingestion.benchmark import (
    load_gold_annotation,
    load_manifest,
    run_extraction_benchmark,
    validate_corpus,
)


REPOSITORY_ROOT = Path(__file__).parents[2]
MANIFEST_PATH = REPOSITORY_ROOT / "tests/source_content/fixtures/manifest.json"


def test_benchmark_manifest_is_valid_and_complete():
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.schema_version == "source-extraction-benchmark-v1"
    assert len(manifest.cases) == 7
    assert {case.format for case in manifest.cases} == {"pdf", "pptx"}


def test_benchmark_corpus_files_and_checksums_are_ready():
    report = validate_corpus(MANIFEST_PATH, REPOSITORY_ROOT)

    assert report["ready"] is True
    assert report["case_count"] == 7


def test_gold_subset_covers_order_hierarchy_tables_notes_visuals_and_locators():
    manifest = load_manifest(MANIFEST_PATH)
    gold_cases = [case for case in manifest.cases if case.gold_path]

    assert len(gold_cases) == 3
    annotations = [
        load_gold_annotation(REPOSITORY_ROOT / case.gold_path)
        for case in gold_cases
    ]
    assert all(annotation.ordered_text for annotation in annotations)
    assert any(annotation.hierarchy for annotation in annotations)
    assert any(annotation.tables for annotation in annotations)
    assert any(annotation.notes for annotation in annotations)
    assert any(annotation.visuals for annotation in annotations)
    assert all(annotation.locators for annotation in annotations)


def test_born_digital_benchmark_executes_and_meets_thresholds():
    report = run_extraction_benchmark(MANIFEST_PATH, REPOSITORY_ROOT)

    assert report["passed"] is True
    assert {case["id"] for case in report["cases"]} == {
        "synthetic-ordered-multicolumn",
        "synthetic-structured-presentation",
    }
    assert all(case["preview_asset_bytes"] > 0 for case in report["cases"])
