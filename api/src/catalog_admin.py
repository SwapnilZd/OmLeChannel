"""Explicit migration and reindex operations for the versioned RLO catalog."""

from __future__ import annotations

import argparse
import json

from rlo_schema import validate_rlo

from .catalog import VersionedRLOCatalog, legacy_rlo_key, parse_versioned_rlo_key
from .indexer import RloIndexer
from .storage import get_storage


def migrate_legacy(catalog: VersionedRLOCatalog) -> tuple[int, int]:
    migrated = skipped = 0
    for key in catalog.storage.list_prefix(""):
        if "/" in key or not key.endswith(".json"):
            continue
        try:
            body = catalog.storage.get(key)
            rlo, _ = validate_rlo(json.loads(body))
            catalog.put(rlo.id, rlo.version, body)
            catalog.storage.delete(legacy_rlo_key(rlo.id))
            migrated += 1
        except Exception as exc:
            skipped += 1
            print(f"[catalog-admin] skipped {key}: {exc}")
    return migrated, skipped


def reindex(catalog: VersionedRLOCatalog, indexer: RloIndexer) -> tuple[int, int]:
    indexed = skipped = 0
    for key in catalog.storage.list_prefix("rlos/"):
        parsed = parse_versioned_rlo_key(key)
        if not parsed:
            continue
        rlo_id, rlo_version = parsed
        try:
            body = catalog.storage.get(key)
            rlo, _ = validate_rlo(json.loads(body))
            if rlo.id != rlo_id or rlo.version != rlo_version:
                raise ValueError("storage key does not match document ID/version")
            current = catalog.current_version(rlo.id)
            uri = key
            if not indexer.upsert(rlo, uri, is_active=rlo.version == current):
                raise RuntimeError("index write unavailable or failed")
            indexer.delete_legacy_point(rlo.id)
            indexed += 1
        except Exception as exc:
            skipped += 1
            print(f"[catalog-admin] skipped {key}: {exc}")
    for item in catalog.list_current():
        if item.rlo_version:
            indexer.set_active_version(item.rlo_id, item.rlo_version)
    return indexed, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate-legacy", action="store_true")
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()
    if not args.migrate_legacy and not args.reindex:
        parser.error("select --migrate-legacy, --reindex, or both")

    catalog = VersionedRLOCatalog(get_storage())
    if args.migrate_legacy:
        migrated, skipped = migrate_legacy(catalog)
        print(f"[catalog-admin] migration: {migrated} migrated, {skipped} skipped")
    if args.reindex:
        indexed, skipped = reindex(catalog, RloIndexer())
        print(f"[catalog-admin] reindex: {indexed} indexed, {skipped} skipped")
        if skipped:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
