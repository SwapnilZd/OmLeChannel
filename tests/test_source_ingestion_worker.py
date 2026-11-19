from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.source_ingestion import worker


def test_process_job_extracts_metadata_and_marks_ready():
    job = SimpleNamespace(
        job_id="job-123",
        source_id="source-123",
        source_version_id="version-123",
        original_filename="notes.md",
        minio_object_path="source-uploads/source/original/notes.md",
    )
    storage = MagicMock()
    storage.get.return_value = b"# Course title\nTwo words"

    with patch.object(worker, "update_job_status") as update:
        worker.process_job(job, storage)

    assert storage.put.call_count == 2
    update.assert_called_once_with(
        "job-123", "ready",
        format_metadata={"word_count": 5, "line_count": 2, "title": "Course title"},
        expected_status="processing",
        artifact_manifest_object_key=(
            "source-content/sources/source-123/versions/version-123/"
            "extractions/job-123/artifact-manifest.json"
        ),
    )


def test_process_job_marks_failed_when_storage_read_fails():
    job = SimpleNamespace(
        job_id="job-123",
        source_id="source-123",
        source_version_id="version-123",
        original_filename="notes.md",
        minio_object_path="source-uploads/source/original/notes.md",
    )
    storage = MagicMock()
    storage.get.side_effect = ConnectionError("storage unavailable")

    with patch.object(worker, "update_job_status") as update:
        worker.process_job(job, storage)

    update.assert_called_once_with(
        "job-123",
        "failed",
        error_message="storage unavailable",
        retryable=True,
    )
