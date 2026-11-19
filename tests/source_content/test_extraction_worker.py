import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.source_ingestion import worker


def test_pdf_worker_persists_canonical_artifacts_before_ready_transition():
    job = SimpleNamespace(
        job_id="run-1",
        source_id="source-1",
        source_version_id="version-1",
        original_filename="fixture.pdf",
        minio_object_path="source-content/original/fixture.pdf",
    )
    storage = MagicMock()
    storage.get.return_value = Path(
        "tests/source_content/fixtures/generated/ordered-multicolumn.pdf"
    ).read_bytes()

    with (
        patch.object(worker, "update_job_status") as update,
        patch.object(worker, "_index_segments") as index_segments,
    ):
        worker.process_job(job, storage)

    stored_keys = [call.args[0] for call in storage.put.call_args_list]
    assert stored_keys[-1].endswith("artifact-manifest.json")
    assert any(key.endswith("document.json") for key in stored_keys)
    assert any(key.endswith("docling-original.json") for key in stored_keys)
    assert any(key.endswith("report.json") for key in stored_keys)
    assert any(key.endswith("segments.json") for key in stored_keys)
    segment_call = next(
        call for call in storage.put.call_args_list if call.args[0].endswith("segments.json")
    )
    assert json.loads(segment_call.args[1])
    assert any("/previews/" in key and key.endswith(".webp") for key in stored_keys)
    assert any("/assets/" in key and key.endswith(".webp") for key in stored_keys)
    update.assert_called_once()
    assert update.call_args.args[:2] == ("run-1", "ready")
    assert update.call_args.kwargs["expected_status"] == "processing"
    index_segments.assert_called_once()


def test_index_failure_propagates_to_worker_stage():
    index = MagicMock()
    index.replace.side_effect = RuntimeError("Qdrant unavailable")

    with pytest.raises(RuntimeError, match="Qdrant unavailable"):
        worker._index_segments("version-1", [], index=index)
