"""Verified access to immutable source-extraction artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from src.storage import get_storage

from .contracts import ArtifactEntry, ArtifactManifest, ExtractedDocument, SourceSegment
from .repository import get_artifact_manifest_object_key, get_job


@dataclass(frozen=True)
class ExtractionArtifacts:
    job: object
    manifest: ArtifactManifest
    document: ExtractedDocument
    report: dict
    segments: list[SourceSegment]


def _verified_body(entry: ArtifactEntry, storage) -> bytes:
    body = storage.get(entry.object_key)
    if hashlib.sha256(body).hexdigest() != entry.sha256:
        raise ValueError(f"artifact checksum mismatch: {entry.artifact_id}")
    return body


def load_manifest(job_id: str, *, storage=None) -> tuple[object, ArtifactManifest]:
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.status != "ready":
        raise ValueError("source extraction is not ready")
    manifest_key = get_artifact_manifest_object_key(job_id)
    if not manifest_key:
        raise ValueError("source extraction has no artifact manifest")
    storage = storage or get_storage()
    manifest = ArtifactManifest.model_validate_json(storage.get(manifest_key))
    if manifest.extraction_run_id != job_id:
        raise ValueError("artifact manifest does not match source job")
    if manifest.source_version_id != job.source_version_id:
        raise ValueError("artifact manifest does not match source version")
    ids = [entry.artifact_id for entry in manifest.artifacts]
    if len(ids) != len(set(ids)):
        raise ValueError("artifact manifest contains duplicate IDs")
    return job, manifest


def artifact_entry(manifest: ArtifactManifest, artifact_id: str) -> ArtifactEntry:
    entry = next(
        (item for item in manifest.artifacts if item.artifact_id == artifact_id), None
    )
    if entry is None:
        raise KeyError(artifact_id)
    return entry


def load_artifact(job_id: str, artifact_id: str, *, storage=None):
    storage = storage or get_storage()
    _job, manifest = load_manifest(job_id, storage=storage)
    entry = artifact_entry(manifest, artifact_id)
    return entry, _verified_body(entry, storage)


def load_extraction(job_id: str, *, storage=None) -> ExtractionArtifacts:
    storage = storage or get_storage()
    job, manifest = load_manifest(job_id, storage=storage)
    by_kind = {entry.kind: entry for entry in manifest.artifacts}
    missing = {"document", "report"} - by_kind.keys()
    if missing:
        raise ValueError(f"source extraction is missing {sorted(missing)[0]} artifact")
    document = ExtractedDocument.model_validate_json(
        _verified_body(by_kind["document"], storage)
    )
    report = json.loads(_verified_body(by_kind["report"], storage))
    if "segments" in by_kind:
        segments = [
            SourceSegment.model_validate(value)
            for value in json.loads(_verified_body(by_kind["segments"], storage))
        ]
    else:
        from .segmentation import segment_document

        segments = segment_document(document)
    return ExtractionArtifacts(
        job=job,
        manifest=manifest,
        document=document,
        report=report,
        segments=segments,
    )
