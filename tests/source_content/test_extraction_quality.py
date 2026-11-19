from src.source_ingestion.contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceFormat,
    SourceLocator,
)
from src.source_ingestion.quality import evaluate_extraction


def test_quality_reports_missing_sparse_and_unmapped_content():
    document = ExtractedDocument(
        source_version_id="version-1",
        extraction_run_id="run-1",
        format=SourceFormat.PDF,
        page_count=2,
        nodes=[
            DocumentNode(
                node_id="root",
                ordinal=0,
                ordinal_path=(0,),
                kind="document",
                role="root",
                text="fixture",
                locators=[SourceLocator(page=1)],
                method=ExtractionMethod.NATIVE,
                child_ids=["unknown"],
            ),
            DocumentNode(
                node_id="unknown",
                parent_id="root",
                ordinal=0,
                ordinal_path=(0, 0),
                kind="unknown",
                role="unknown",
                text="x",
                locators=[SourceLocator(page=1)],
                method=ExtractionMethod.UNKNOWN,
            ),
        ],
    )

    report = evaluate_extraction(document, mapping_warnings=("unmapped_item:0",))

    codes = {warning.code for warning in report.warnings}
    assert {"missing_extent", "sparse_extent", "unsupported_object", "mapping_loss"} <= codes
    assert report.text_coverage == 0.5
    assert report.locator_accuracy == 1.0
    assert report.ocr_coverage == 1.0
