"""Tests for ProviderAssetCache — deduplication of HeyGen asset uploads."""
from __future__ import annotations

import io
import pytest

from learning_pipeline.providers.heygen.asset_cache import (
    MinioProviderAssetCache,
    ProviderAssetCache,
    compute_sha256,
)


class _Response(io.BytesIO):
    def release_conn(self):
        pass


class _MemoryMinio:
    def __init__(self):
        self.bucket = False
        self.objects = {}

    def bucket_exists(self, _bucket):
        return self.bucket

    def make_bucket(self, _bucket):
        self.bucket = True

    def put_object(self, bucket, name, stream, *, length, content_type):
        self.objects[(bucket, name)] = stream.read(length)

    def get_object(self, bucket, name):
        return _Response(self.objects[(bucket, name)])


def _cache(tmp_path) -> ProviderAssetCache:
    return ProviderAssetCache(tmp_path / "cache")


def test_get_returns_none_when_cache_empty(tmp_path):
    cache = _cache(tmp_path)
    result = cache.get("artifact://bgs/bg.png", "abc123")
    assert result is None


def test_put_and_get_roundtrip(tmp_path):
    cache = _cache(tmp_path)
    record = cache.put("artifact://bgs/bg.png", "sha256abc", "asset-id-1")
    assert record.provider_asset_id == "asset-id-1"

    retrieved = cache.get("artifact://bgs/bg.png", "sha256abc")
    assert retrieved is not None
    assert retrieved.provider_asset_id == "asset-id-1"
    assert retrieved.provider == "heygen"
    assert retrieved.source_sha256 == "sha256abc"


def test_different_sha_returns_none(tmp_path):
    cache = _cache(tmp_path)
    cache.put("artifact://bgs/bg.png", "sha256-v1", "asset-v1")
    # Different sha → not a match
    result = cache.get("artifact://bgs/bg.png", "sha256-v2")
    assert result is None


def test_different_uri_returns_none(tmp_path):
    cache = _cache(tmp_path)
    cache.put("artifact://bgs/a.png", "sha256-abc", "asset-a")
    result = cache.get("artifact://bgs/b.png", "sha256-abc")
    assert result is None


def test_overwrite_same_key(tmp_path):
    cache = _cache(tmp_path)
    cache.put("artifact://bgs/bg.png", "sha256abc", "asset-old")
    cache.put("artifact://bgs/bg.png", "sha256abc", "asset-new")
    retrieved = cache.get("artifact://bgs/bg.png", "sha256abc")
    assert retrieved.provider_asset_id == "asset-new"


def test_multiple_entries(tmp_path):
    cache = _cache(tmp_path)
    cache.put("artifact://bgs/a.png", "sha-a", "asset-a")
    cache.put("artifact://bgs/b.png", "sha-b", "asset-b")
    assert cache.get("artifact://bgs/a.png", "sha-a").provider_asset_id == "asset-a"
    assert cache.get("artifact://bgs/b.png", "sha-b").provider_asset_id == "asset-b"


def test_cache_persists_across_instances(tmp_path):
    cache1 = ProviderAssetCache(tmp_path / "cache")
    cache1.put("artifact://bgs/bg.png", "sha-x", "asset-persisted")

    cache2 = ProviderAssetCache(tmp_path / "cache")
    result = cache2.get("artifact://bgs/bg.png", "sha-x")
    assert result is not None
    assert result.provider_asset_id == "asset-persisted"


def test_compute_sha256():
    data = b"hello world"
    sha = compute_sha256(data)
    assert len(sha) == 64  # 32 bytes → 64 hex chars
    assert sha == compute_sha256(data)  # deterministic


def test_compute_sha256_different_data():
    assert compute_sha256(b"a") != compute_sha256(b"b")


def test_malformed_cache_file_returns_none(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "heygen_assets.json").write_text("not json")
    cache = ProviderAssetCache(cache_dir)
    result = cache.get("artifact://bgs/bg.png", "sha-x")
    assert result is None


def test_minio_cache_roundtrip():
    cache = MinioProviderAssetCache(
        endpoint="http://minio:9000",
        access_key="access",
        secret_key="secret",
        bucket="artifacts",
        client=_MemoryMinio(),
    )

    cache.put("artifact://bgs/bg.png", "sha-x", "asset-minio")

    assert cache.get("artifact://bgs/bg.png", "sha-x").provider_asset_id == "asset-minio"
