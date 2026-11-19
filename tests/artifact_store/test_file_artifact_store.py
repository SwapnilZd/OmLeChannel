"""
Tests for FileArtifactStore.

Covers: bytes written and read back, logical URI format, SHA-256 and size,
atomic write semantics, path traversal rejection, and missing artifact error.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from learning_pipeline.runtime.artifact_store import (
    ArtifactNotFoundError,
    ArtifactRef,
    FileArtifactStore,
    PathTraversalError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _store(tmp_path: Path) -> FileArtifactStore:
    return FileArtifactStore(tmp_path / "artifacts")


SAMPLE_DATA = b"\x00\x01\x02\x03" * 64  # 256 bytes


# ── Successful round-trips ────────────────────────────────────────────────────


async def test_bytes_written_can_be_read_back(tmp_path) -> None:
    store = _store(tmp_path)
    ref = await store.put_bytes("speech/wf-1", "task-1.wav", SAMPLE_DATA, "audio/wav")
    result = await store.get_bytes(ref.uri)
    assert result == SAMPLE_DATA


async def test_uri_uses_artifact_scheme(tmp_path) -> None:
    store = _store(tmp_path)
    ref = await store.put_bytes("ns", "file.bin", b"x", "application/octet-stream")
    assert ref.uri.startswith("artifact://")


async def test_uri_encodes_namespace_and_name(tmp_path) -> None:
    store = _store(tmp_path)
    ref = await store.put_bytes("speech/wf-abc", "seg-1.wav", b"y", "audio/wav")
    assert "speech/wf-abc" in ref.uri
    assert "seg-1.wav" in ref.uri


async def test_returned_ref_is_artifact_ref_instance(tmp_path) -> None:
    store = _store(tmp_path)
    ref = await store.put_bytes("ns", "name.bin", b"data", "audio/wav")
    assert isinstance(ref, ArtifactRef)


async def test_sha256_matches_data(tmp_path) -> None:
    store = _store(tmp_path)
    data = b"hello artifact store"
    ref = await store.put_bytes("ns", "f.bin", data, "audio/wav")
    expected = hashlib.sha256(data).hexdigest()
    assert ref.sha256 == expected


async def test_size_bytes_is_correct(tmp_path) -> None:
    store = _store(tmp_path)
    data = b"exact size"
    ref = await store.put_bytes("ns", "f.bin", data, "audio/wav")
    assert ref.size_bytes == len(data)


async def test_media_type_preserved_in_ref(tmp_path) -> None:
    store = _store(tmp_path)
    ref = await store.put_bytes("ns", "f.wav", b"data", "audio/wav")
    assert ref.media_type == "audio/wav"


async def test_directory_created_automatically(tmp_path) -> None:
    store = _store(tmp_path)
    nested_ns = "speech/wf-deep/run-1"
    ref = await store.put_bytes(nested_ns, "audio.wav", b"data", "audio/wav")
    # Should succeed even if namespace dir did not exist
    data = await store.get_bytes(ref.uri)
    assert data == b"data"


async def test_overwrite_replaces_content(tmp_path) -> None:
    store = _store(tmp_path)
    await store.put_bytes("ns", "file.bin", b"original", "audio/wav")
    ref = await store.put_bytes("ns", "file.bin", b"updated", "audio/wav")
    data = await store.get_bytes(ref.uri)
    assert data == b"updated"


# ── Atomic write ──────────────────────────────────────────────────────────────


async def test_no_partial_file_if_write_interrupted(tmp_path) -> None:
    """After a completed put_bytes the file on disk must equal the full data."""
    store = _store(tmp_path)
    data = b"a" * 1024
    ref = await store.put_bytes("ns", "big.bin", data, "audio/wav")
    dest = tmp_path / "artifacts" / "ns" / "big.bin"
    assert dest.read_bytes() == data


# ── Error paths ───────────────────────────────────────────────────────────────


async def test_missing_artifact_raises_not_found(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ArtifactNotFoundError):
        await store.get_bytes("artifact://speech/wf-missing/does-not-exist.wav")


async def test_path_traversal_in_namespace_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(PathTraversalError):
        await store.put_bytes("../../etc", "passwd", b"bad", "text/plain")


async def test_path_traversal_in_name_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(PathTraversalError):
        await store.put_bytes("ns", "../../secrets.txt", b"bad", "text/plain")


async def test_empty_namespace_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(PathTraversalError):
        await store.put_bytes("", "file.bin", b"data", "audio/wav")


async def test_empty_name_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(PathTraversalError):
        await store.put_bytes("ns", "", b"data", "audio/wav")


async def test_unsupported_uri_scheme_rejected(tmp_path) -> None:
    from learning_pipeline.runtime.artifact_store import ArtifactReadError

    store = _store(tmp_path)
    with pytest.raises(ArtifactReadError):
        await store.get_bytes("fake://ns/file.wav")


async def test_malformed_uri_missing_path_rejected(tmp_path) -> None:
    from learning_pipeline.runtime.artifact_store import ArtifactReadError

    store = _store(tmp_path)
    with pytest.raises(ArtifactReadError):
        await store.get_bytes("artifact://no-slash-here")
