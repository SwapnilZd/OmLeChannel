"""Provider asset cache — avoids duplicate uploads to HeyGen.

ProviderAssetCache persists a mapping of
    (provider, source_artifact_uri, source_sha256) → HeyGen asset_id

so that retries and repeated runs do not re-upload identical assets.

Storage: a single JSON file at ``{cache_root}/heygen_assets.json``.

Thread safety: writes use atomic rename via a temporary file, matching
the pattern used by FileArtifactStore.

The cache does not enforce expiry — HeyGen asset IDs are treated as durable
unless the record is explicitly removed.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_pipeline.contracts.common import FrozenModel

logger = logging.getLogger(__name__)

_PROVIDER = "heygen"


class ProviderAssetRecord(FrozenModel):
    """Persistent record of one uploaded provider asset."""

    provider: str
    source_artifact_uri: str
    source_sha256: str
    provider_asset_id: str
    uploaded_at: str  # ISO-8601 UTC timestamp


class ProviderAssetCache:
    """File-backed cache mapping artifact bytes to HeyGen asset IDs.

    Parameters
    ----------
    cache_root:
        Directory where ``heygen_assets.json`` is stored.
    """

    def __init__(self, cache_root: Path) -> None:
        self._cache_file = Path(cache_root) / "heygen_assets.json"

    # ── Public interface ───────────────────────────────────────────────────────

    def get(self, artifact_uri: str, sha256: str) -> ProviderAssetRecord | None:
        """Return the cached record for this artifact, or None."""
        cache = self._load()
        key = _cache_key(artifact_uri, sha256)
        raw = cache.get(key)
        if raw is None:
            return None
        try:
            return ProviderAssetRecord.model_validate(raw)
        except Exception as exc:
            logger.warning("Asset cache: malformed record for %s — ignoring: %s", key, exc)
            return None

    def put(
        self,
        artifact_uri: str,
        sha256: str,
        asset_id: str,
    ) -> ProviderAssetRecord:
        """Store a new asset_id mapping and return the record."""
        record = ProviderAssetRecord(
            provider=_PROVIDER,
            source_artifact_uri=artifact_uri,
            source_sha256=sha256,
            provider_asset_id=asset_id,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
        )
        cache = self._load()
        key = _cache_key(artifact_uri, sha256)
        cache[key] = record.model_dump()
        self._save(cache)
        logger.debug("Asset cache: stored %s → %s", artifact_uri, asset_id)
        return record

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._cache_file.exists():
            return {}
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Asset cache: could not read cache file — starting empty: %s", exc)
            return {}

    def _save(self, data: dict) -> None:
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._cache_file)


class MinioProviderAssetCache:
    """Store each HeyGen asset mapping as an independent MinIO object."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from minio import Minio

            secure = endpoint.startswith("https://")
            host = endpoint.removeprefix("http://").removeprefix("https://")
            client = Minio(
                host,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_env(cls) -> "MinioProviderAssetCache":
        return cls(
            endpoint=os.environ["MINIO_ENDPOINT"],
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket=os.getenv("MINIO_ARTIFACT_BUCKET", "workflow-artifacts"),
        )

    def get(self, artifact_uri: str, sha256: str) -> ProviderAssetRecord | None:
        response = None
        try:
            response = self._client.get_object(
                self._bucket, self._object_name(artifact_uri, sha256)
            )
            return ProviderAssetRecord.model_validate_json(response.read())
        except Exception as exc:
            if getattr(exc, "code", None) not in {"NoSuchKey", "NoSuchObject"}:
                logger.warning("Asset cache: could not read MinIO record: %s", exc)
            return None
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def put(
        self,
        artifact_uri: str,
        sha256: str,
        asset_id: str,
    ) -> ProviderAssetRecord:
        record = ProviderAssetRecord(
            provider=_PROVIDER,
            source_artifact_uri=artifact_uri,
            source_sha256=sha256,
            provider_asset_id=asset_id,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
        )
        data = record.model_dump_json().encode("utf-8")
        if not self._client.bucket_exists(self._bucket):
            try:
                self._client.make_bucket(self._bucket)
            except Exception as exc:
                if getattr(exc, "code", None) not in {
                    "BucketAlreadyExists",
                    "BucketAlreadyOwnedByYou",
                }:
                    raise
        self._client.put_object(
            self._bucket,
            self._object_name(artifact_uri, sha256),
            io.BytesIO(data),
            length=len(data),
            content_type="application/json",
        )
        return record

    @staticmethod
    def _object_name(artifact_uri: str, sha256: str) -> str:
        key = hashlib.sha256(_cache_key(artifact_uri, sha256).encode()).hexdigest()
        return f"heygen-asset-cache/{key}.json"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cache_key(artifact_uri: str, sha256: str) -> str:
    return f"{_PROVIDER}:{artifact_uri}:{sha256}"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
