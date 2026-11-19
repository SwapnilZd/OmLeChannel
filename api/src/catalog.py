"""Version-aware object-storage policy for the RLO catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .storage.base import StorageBackend

RLO_PREFIX = "rlos/"
_VERSIONED_KEY = re.compile(r"^rlos/(?P<id>[^/]+)/(?P<version>[^/]+)\.json$")


def versioned_rlo_key(rlo_id: str, rlo_version: str) -> str:
    if not rlo_id or "/" in rlo_id or not rlo_version or "/" in rlo_version:
        raise ValueError("RLO ID and version must be non-empty path-safe values.")
    return f"{RLO_PREFIX}{rlo_id}/{rlo_version}.json"


def legacy_rlo_key(rlo_id: str) -> str:
    return f"{rlo_id}.json"


def parse_versioned_rlo_key(key: str) -> tuple[str, str] | None:
    match = _VERSIONED_KEY.fullmatch(key)
    if not match:
        return None
    return match.group("id"), match.group("version")


def version_sort_key(version: str) -> tuple:
    """Sort semver-like versions deterministically without a new dependency."""
    core, separator, suffix = version.partition("-")
    pieces = tuple((0, int(p)) if p.isdigit() else (1, p.casefold()) for p in core.split("."))
    # A release sorts after its prerelease with the same numeric core.
    return pieces, 1 if not separator else 0, suffix.casefold()


@dataclass(frozen=True)
class StoredRLOVersion:
    rlo_id: str
    rlo_version: str
    key: str
    is_current: bool


class VersionedRLOCatalog:
    """Small policy layer over MinIO/GCS-compatible object storage."""

    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage

    def put(self, rlo_id: str, rlo_version: str, body: bytes) -> str:
        return self.storage.put(versioned_rlo_key(rlo_id, rlo_version), body)

    def versions(self, rlo_id: str) -> list[str]:
        prefix = f"{RLO_PREFIX}{rlo_id}/"
        versions = [
            parsed[1]
            for key in self.storage.list_prefix(prefix)
            if (parsed := parse_versioned_rlo_key(key)) and parsed[0] == rlo_id
        ]
        return sorted(set(versions), key=version_sort_key, reverse=True)

    def current_version(self, rlo_id: str) -> str | None:
        versions = self.versions(rlo_id)
        return versions[0] if versions else None

    def get_exact(self, rlo_id: str, rlo_version: str) -> bytes:
        return self.storage.get(versioned_rlo_key(rlo_id, rlo_version))

    def get_current(self, rlo_id: str) -> tuple[bytes, str | None]:
        current = self.current_version(rlo_id)
        if current is not None:
            return self.get_exact(rlo_id, current), current
        # Read compatibility for catalogs created before versioned storage.
        return self.storage.get(legacy_rlo_key(rlo_id)), None

    def list_current(self) -> list[StoredRLOVersion]:
        by_id: dict[str, list[str]] = {}
        legacy_ids: set[str] = set()
        for key in self.storage.list_prefix(""):
            parsed = parse_versioned_rlo_key(key)
            if parsed:
                by_id.setdefault(parsed[0], []).append(parsed[1])
            elif key.endswith(".json") and "/" not in key:
                legacy_ids.add(key.removesuffix(".json"))

        result = []
        for rlo_id, versions in by_id.items():
            current = max(set(versions), key=version_sort_key)
            result.append(StoredRLOVersion(rlo_id, current, versioned_rlo_key(rlo_id, current), True))
        for rlo_id in legacy_ids - by_id.keys():
            result.append(StoredRLOVersion(rlo_id, "", legacy_rlo_key(rlo_id), True))
        return sorted(result, key=lambda item: item.rlo_id)

    def delete_all(self, rlo_id: str) -> bool:
        keys = [versioned_rlo_key(rlo_id, version) for version in self.versions(rlo_id)]
        legacy = legacy_rlo_key(rlo_id)
        if self.storage.exists(legacy):
            keys.append(legacy)
        for key in keys:
            self.storage.delete(key)
        return bool(keys)
