"""
ArtifactStore — write and read binary artifacts outside workflow state.

Raw audio bytes never enter PostgreSQL, BuildPlan, TaskResult, or API responses.
Executors store bytes here and return logical artifact:// URIs so that the rest
of the system deals only with metadata references.

Production deployments use MinioArtifactStore. FileArtifactStore remains for
tests and explicit local CLI use.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


# ── Typed artifact reference ──────────────────────────────────────────────────


class ArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    """Metadata reference returned after storing an artifact."""

    uri: str
    """Logical URI, e.g. ``artifact://speech/wf-1/task-1.wav``."""

    media_type: str
    sha256: str
    size_bytes: int


# ── Error types ───────────────────────────────────────────────────────────────


class ArtifactWriteError(RuntimeError):
    """Raised when an artifact cannot be persisted."""


class ArtifactReadError(RuntimeError):
    """Raised when an artifact cannot be retrieved."""


class ArtifactNotFoundError(KeyError):
    """Raised when an artifact URI does not resolve to a stored file."""


class PathTraversalError(ValueError):
    """Raised when namespace or name contain unsafe path components."""


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class ArtifactStore(Protocol):
    async def put_bytes(
        self,
        namespace: str,
        name: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef: ...

    async def get_bytes(self, uri: str) -> bytes: ...


# ── File implementation ───────────────────────────────────────────────────────

_URI_SCHEME = "artifact"


class FileArtifactStore:
    """Store artifacts on the local filesystem with ``artifact://`` URIs.

    Writes are atomic (write to ``.tmp`` then ``os.replace``).  Path traversal
    is prevented by resolving the final path and asserting it stays under root.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put_bytes(
        self,
        namespace: str,
        name: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef:
        dest = self._safe_path(namespace, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise ArtifactWriteError(
                f"Cannot write artifact {namespace!r}/{name!r}: {exc}"
            ) from exc

        sha256 = hashlib.sha256(data).hexdigest()
        uri = f"{_URI_SCHEME}://{namespace}/{name}"
        return ArtifactRef(
            uri=uri,
            media_type=media_type,
            sha256=sha256,
            size_bytes=len(data),
        )

    async def get_bytes(self, uri: str) -> bytes:
        path = self.resolve_path(uri)
        if not path.exists():
            raise ArtifactNotFoundError(uri)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ArtifactReadError(
                f"Cannot read artifact {uri!r}: {exc}"
            ) from exc

    def resolve_path(self, uri: str) -> Path:
        """Resolve a logical URI to a safe local path for streaming responses."""
        namespace, name = _parse_uri(uri)
        path = self._safe_path(namespace, name)
        if not path.exists() or not path.is_file():
            raise ArtifactNotFoundError(uri)
        return path

    def _safe_path(self, namespace: str, name: str) -> Path:
        for segment in (namespace, name):
            if not segment:
                raise PathTraversalError(
                    f"Artifact path segment must not be empty: {segment!r}"
                )
            parts = segment.replace("\\", "/").split("/")
            if ".." in parts:
                raise PathTraversalError(
                    f"Path traversal detected in segment: {segment!r}"
                )
        path = (self._root / namespace / name).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise PathTraversalError(
                f"Resolved path escapes artifact root: {path}"
            ) from exc
        return path


class MinioArtifactStore:
    """Store logical artifacts as objects in a MinIO bucket."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        client: Any | None = None,
    ) -> None:
        if not endpoint or not access_key or not secret_key or not bucket:
            raise ValueError("MinIO artifact storage requires endpoint, credentials, and bucket.")
        self._bucket = bucket
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

    async def put_bytes(
        self,
        namespace: str,
        name: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef:
        object_name = _object_name(namespace, name)
        try:
            await asyncio.to_thread(self._put, object_name, data, media_type)
        except Exception as exc:
            raise ArtifactWriteError(
                f"Cannot write artifact {namespace!r}/{name!r}: {exc}"
            ) from exc
        return ArtifactRef(
            uri=f"{_URI_SCHEME}://{object_name}",
            media_type=media_type,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )

    def _put(self, object_name: str, data: bytes, media_type: str) -> None:
        import io

        self._ensure_bucket()
        self._client.put_object(
            self._bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=media_type,
        )

    async def get_bytes(self, uri: str) -> bytes:
        namespace, name = _parse_uri(uri)
        object_name = _object_name(namespace, name)
        try:
            return await asyncio.to_thread(self._get, object_name)
        except ArtifactNotFoundError:
            raise
        except Exception as exc:
            raise ArtifactReadError(f"Cannot read artifact {uri!r}: {exc}") from exc

    def _get(self, object_name: str) -> bytes:
        response = None
        try:
            response = self._client.get_object(self._bucket, object_name)
            return response.read()
        except Exception as exc:
            if getattr(exc, "code", None) in {"NoSuchKey", "NoSuchObject"}:
                raise ArtifactNotFoundError(
                    f"{_URI_SCHEME}://{object_name}"
                ) from exc
            raise
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            try:
                self._client.make_bucket(self._bucket)
            except Exception as exc:
                if getattr(exc, "code", None) not in {
                    "BucketAlreadyExists",
                    "BucketAlreadyOwnedByYou",
                }:
                    raise


def create_artifact_store() -> ArtifactStore:
    """Build the configured application artifact store."""
    backend = os.getenv("ARTIFACT_STORE_BACKEND", "file").strip().casefold()
    if backend == "minio":
        return MinioArtifactStore(
            endpoint=os.environ["MINIO_ENDPOINT"],
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket=os.getenv("MINIO_ARTIFACT_BUCKET", "workflow-artifacts"),
        )
    if backend == "file":
        return FileArtifactStore(Path(os.getenv("ARTIFACT_STORE_ROOT", "/artifacts")))
    raise ValueError(f"Unsupported ARTIFACT_STORE_BACKEND: {backend!r}")

def _parse_uri(uri: str) -> tuple[str, str]:
    prefix = f"{_URI_SCHEME}://"
    if not uri.startswith(prefix):
        raise ArtifactReadError(f"Unsupported artifact URI scheme: {uri!r}")
    rest = uri[len(prefix):]
    slash = rest.find("/")
    if slash < 0:
        raise ArtifactReadError(f"Malformed artifact URI (no path component): {uri!r}")
    return rest[:slash], rest[slash + 1:]


def _object_name(namespace: str, name: str) -> str:
    for segment in (namespace, name):
        if not segment:
            raise PathTraversalError("Artifact path segments must not be empty.")
        parts = segment.replace("\\", "/").split("/")
        if ".." in parts or any(not part for part in parts):
            raise PathTraversalError(f"Unsafe artifact path segment: {segment!r}")
    return f"{namespace}/{name}"
