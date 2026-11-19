import os

from .base import StorageBackend


def get_storage() -> StorageBackend:
    backend = os.environ.get("STORAGE_BACKEND", "minio").lower()
    if backend == "minio":
        from .minio_backend import MinioBackend
        return MinioBackend()
    if backend == "gcs":
        from .gcs_backend import GcsBackend
        return GcsBackend()
    raise ValueError(f"Unknown STORAGE_BACKEND: {backend!r}. Expected 'minio' or 'gcs'.")
