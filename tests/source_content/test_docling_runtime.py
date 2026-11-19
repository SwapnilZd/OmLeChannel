import importlib.metadata
import subprocess
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.pipeline_options import LayoutObjectDetectionOptions
from docling.datamodel.object_detection_engine_options import (
    TransformersObjectDetectionEngineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption


ARTIFACTS_PATH = Path("/opt/docling-models")
FIXTURE_PATH = Path("tests/source_content/fixtures/generated/ordered-multicolumn.pdf")


def test_pinned_docling_and_tesseract_are_available():
    assert importlib.metadata.version("docling") == "2.119.0"
    assert ARTIFACTS_PATH.is_dir()
    assert any(ARTIFACTS_PATH.iterdir())

    result = subprocess.run(
        ["tesseract", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.startswith("tesseract 5")


def test_standard_pdf_pipeline_converts_with_local_models_only():
    options = PdfPipelineOptions(
        artifacts_path=ARTIFACTS_PATH,
        do_ocr=False,
        do_table_structure=True,
        layout_options=LayoutObjectDetectionOptions(
            engine_options=TransformersObjectDetectionEngineOptions(
                compile_model=False,
            )
        ),
        enable_remote_services=False,
        allow_external_plugins=False,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        }
    )

    document = converter.convert(FIXTURE_PATH).document
    markdown = document.export_to_markdown()

    assert "Ordered extraction fixture" in markdown
    assert "Second section" in markdown
