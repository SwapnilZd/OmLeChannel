import hashlib
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src import source_upload
from src.app import app


@pytest.fixture
def repository():
    repo = MagicMock()
    repo.find_by_checksum.return_value = None
    repo.list_jobs.return_value = []
    repo.get_job.return_value = None
    return repo


@pytest.fixture
def storage():
    return MagicMock()


@pytest.fixture
def client(monkeypatch, repository, storage):
    monkeypatch.setenv("POC_AUTH_ENABLED", "false")
    patches = [
        patch.object(source_upload, "find_by_checksum", repository.find_by_checksum),
        patch.object(source_upload, "create_job", repository.create_job),
        patch.object(source_upload, "list_jobs", repository.list_jobs),
        patch.object(source_upload, "get_job", repository.get_job),
        patch.object(source_upload, "delete_job", repository.delete_job),
        patch.object(source_upload, "delete_all_jobs", repository.delete_all_jobs),
        patch.object(source_upload, "get_storage", return_value=storage),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        yield TestClient(app, raise_server_exceptions=False)


def upload(filename, content=b"test content", content_type=None):
    mime = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt": "text/plain",
        "md": "text/markdown",
        "html": "text/html",
        "epub": "application/epub+zip",
    }
    extension = filename.rsplit(".", 1)[-1].lower()
    return {"file": (filename, io.BytesIO(content), content_type or mime.get(extension, "application/octet-stream"))}


@pytest.mark.parametrize("filename", ["sample.pdf", "sample.docx", "sample.pptx", "sample.txt", "sample.md", "sample.html", "sample.epub"])
def test_supported_source_upload_is_queued(client, repository, storage, filename):
    response = client.post("/api/source-uploads", files=upload(filename))

    assert response.status_code == 201
    assert response.json()["status"] == "queued"
    assert response.json()["filename"] == filename
    assert response.json()["object_path"].endswith(f"/original/{filename}")
    storage.put.assert_called_once()
    repository.create_job.assert_called_once()


def test_upload_records_checksum_size_and_media_type(client, repository, storage):
    content = b"hello world"

    response = client.post("/api/source-uploads", files=upload("test.txt", content))

    assert response.status_code == 201
    assert response.json()["checksum"] == hashlib.sha256(content).hexdigest()
    assert response.json()["size_bytes"] == len(content)
    assert storage.put.call_args.args[2] == "text/plain"


@pytest.mark.parametrize("filename,content,status", [("malware.exe", b"x", 415), ("empty.pdf", b"", 400), ("huge.pdf", b"x" * (50 * 1024 * 1024 + 1), 413)])
def test_invalid_source_upload_is_rejected(client, filename, content, status):
    response = client.post("/api/source-uploads", files=upload(filename, content))

    assert response.status_code == status


def test_duplicate_source_upload_is_rejected(client, repository):
    repository.find_by_checksum.return_value = MagicMock(job_id="existing-job")

    response = client.post("/api/source-uploads", files=upload("duplicate.pdf"))

    assert response.status_code == 409


def test_new_edition_can_target_an_existing_logical_source(client, repository):
    response = client.post(
        "/api/source-uploads",
        data={"source_id": "existing-source"},
        files=upload("edition-2.pdf", b"new edition"),
    )

    assert response.status_code == 201
    assert response.json()["source_id"] == "existing-source"
    assert repository.create_job.call_args.kwargs["source_id"] == "existing-source"


def test_database_failure_removes_stored_object(client, repository, storage):
    repository.create_job.side_effect = RuntimeError("database unavailable")

    response = client.post("/api/source-uploads", files=upload("sample.pdf"))

    assert response.status_code == 500
    storage.delete.assert_called_once_with(storage.put.call_args.args[0])


def test_list_jobs_returns_metadata(client, repository):
    repository.list_jobs.return_value = [MagicMock(
        job_id="job-123",
        source_id="source-456",
        source_version_id="version-789",
        status="ready",
        original_filename="test.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        checksum="abc123",
        uploader=None,
        uploaded_at=datetime.now(timezone.utc),
        minio_object_path="source-uploads/source-456/original/test.pdf",
        error_message=None,
        format_metadata={"page_count": 5},
    )]

    response = client.get("/api/source-uploads")

    assert response.status_code == 200
    assert response.json()[0]["format_metadata"] == {"page_count": 5}
    assert response.json()[0]["object_path"].endswith("test.pdf")


def test_delete_job_removes_object_and_record(client, repository, storage):
    repository.get_job.return_value = MagicMock(
        source_id="source-456",
        minio_object_path="source-uploads/source/original/test.pdf",
    )

    response = client.delete("/api/source-uploads/job-123")

    assert response.status_code == 204
    storage.delete.assert_called_once_with("source-uploads/source/original/test.pdf")
    repository.delete_job.assert_called_once_with("job-123")


def test_source_api_requires_poc_session_when_enabled(client, monkeypatch):
    monkeypatch.setenv("POC_AUTH_ENABLED", "true")

    response = client.get("/api/source-uploads")

    assert response.status_code == 401
