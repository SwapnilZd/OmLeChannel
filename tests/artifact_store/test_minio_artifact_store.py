from __future__ import annotations

import io

import pytest

from learning_pipeline.runtime.artifact_store import (
    ArtifactNotFoundError,
    MinioArtifactStore,
    PathTraversalError,
)


class MissingObject(Exception):
    code = "NoSuchKey"


class ObjectResponse(io.BytesIO):
    def release_conn(self):
        pass


class MemoryMinio:
    def __init__(self):
        self.buckets = set()
        self.objects = {}

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets.add(bucket)

    def put_object(self, bucket, name, stream, *, length, content_type):
        self.objects[(bucket, name)] = (stream.read(length), content_type)

    def get_object(self, bucket, name):
        try:
            data, _media_type = self.objects[(bucket, name)]
        except KeyError as exc:
            raise MissingObject(name) from exc
        return ObjectResponse(data)


def _store(client: MemoryMinio) -> MinioArtifactStore:
    return MinioArtifactStore(
        endpoint="http://minio:9000",
        access_key="access",
        secret_key="secret",
        bucket="artifacts",
        client=client,
    )


@pytest.mark.asyncio
async def test_minio_store_round_trip_preserves_logical_uri_and_metadata():
    store = _store(MemoryMinio())

    ref = await store.put_bytes("jobs/job-1", "course.zip", b"course", "application/zip")

    assert ref.uri == "artifact://jobs/job-1/course.zip"
    assert ref.size_bytes == 6
    assert await store.get_bytes(ref.uri) == b"course"


@pytest.mark.asyncio
async def test_minio_store_reports_missing_objects():
    with pytest.raises(ArtifactNotFoundError):
        await _store(MemoryMinio()).get_bytes("artifact://jobs/job-1/missing.zip")


@pytest.mark.asyncio
async def test_minio_store_rejects_unsafe_object_names():
    with pytest.raises(PathTraversalError):
        await _store(MemoryMinio()).put_bytes(
            "jobs/job-1", "../secret", b"no", "application/octet-stream"
        )
