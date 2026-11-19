from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import tempfile
from dataclasses import replace
from pathlib import Path

from .extractors import extract_metadata
from .repository import claim_next_queued_job, update_job_status

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = float(os.environ.get("SOURCE_WORKER_POLL_SECONDS", "5"))


async def background_worker(storage) -> None:
    """Process queued source-ingestion jobs for this API instance."""
    logger.info("[source-ingestion] Worker started")
    while True:
        try:
            worker_id = os.environ.get("SOURCE_WORKER_ID", socket.gethostname())
            while job := claim_next_queued_job(worker_id=worker_id):
                await asyncio.to_thread(process_job, job, storage)
            from src.source_authoring.job_repository import claim_next_objective_job
            from src.source_authoring.job_service import process_objective_job

            while objective_job := claim_next_objective_job(worker_id=worker_id):
                await asyncio.to_thread(process_objective_job, objective_job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[source-ingestion] Worker iteration failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def process_job(job, storage) -> None:
    """Extract metadata for one job already claimed as processing."""
    try:
        file_bytes = storage.get(job.minio_object_path)
        extension = job.original_filename.rsplit(".", 1)[-1].lower()
        if extension in {"pdf", "pptx", "epub"}:
            _process_canonical_job(job, storage, file_bytes, extension)
            logger.info("[source-ingestion] Job %s ready", job.job_id)
            return
        metadata = extract_metadata(extension, file_bytes)
        metadata_body = json.dumps(metadata, sort_keys=True).encode("utf-8")
        artifact_key = (
            f"source-content/sources/{job.source_id}/versions/"
            f"{job.source_version_id}/extractions/{job.job_id}/format-metadata.json"
        )
        manifest_key = artifact_key.replace("format-metadata.json", "artifact-manifest.json")
        manifest_body = json.dumps(
            {
                "schema_version": "source-artifacts-v1",
                "source_version_id": job.source_version_id,
                "extraction_run_id": job.job_id,
                "artifacts": [
                    {
                        "artifact_id": "format-metadata",
                        "kind": "format_metadata",
                        "object_key": artifact_key,
                        "sha256": hashlib.sha256(metadata_body).hexdigest(),
                        "content_type": "application/json",
                        "size_bytes": len(metadata_body),
                    }
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
        storage.put(artifact_key, metadata_body, "application/json")
        storage.put(manifest_key, manifest_body, "application/json")
        update_job_status(
            job.job_id,
            "ready",
            format_metadata=metadata,
            expected_status="processing",
            artifact_manifest_object_key=manifest_key,
        )
        logger.info("[source-ingestion] Job %s ready", job.job_id)
    except Exception as exc:
        logger.exception("[source-ingestion] Job %s failed", job.job_id)
        update_job_status(
            job.job_id,
            "failed",
            error_message=str(exc),
            retryable=isinstance(exc, (ConnectionError, OSError, TimeoutError)),
        )


def _process_canonical_job(job, storage, file_bytes: bytes, extension: str) -> None:
    from .contracts import ArtifactEntry, ArtifactManifest
    from .quality import evaluate_extraction

    with tempfile.NamedTemporaryFile(suffix=f".{extension}") as source_file:
        source_file.write(file_bytes)
        source_file.flush()
        if extension == "epub":
            from .extractors.epub import extract_epub

            extraction = extract_epub(
                Path(source_file.name),
                source_version_id=job.source_version_id,
                extraction_run_id=job.job_id,
            )
        else:
            from .extractors.docling import extract_document

            extraction = extract_document(
                Path(source_file.name),
                source_version_id=job.source_version_id,
                extraction_run_id=job.job_id,
            )
        native_segments = list(getattr(extraction, "segments", ()))
        if extension == "pdf":
            from .ocr import apply_selective_ocr

            pre_ocr_document = extraction.document
            ocr = apply_selective_ocr(extraction.document, extraction.artifacts)
            extraction = replace(
                extraction,
                document=ocr.document,
                warnings=(*extraction.warnings, *ocr.warnings),
            )
            if extraction.document != pre_ocr_document:
                native_segments = []
    extraction = _add_visual_explanations(extraction)
    from .segmentation import resequence_segments, segment_document

    if native_segments:
        covered_node_ids = {
            node_id for segment in native_segments for node_id in segment.node_ids
        }
        uncovered_node_ids = {
            node.node_id
            for node in extraction.document.nodes
            if node.text and node.kind != "document" and node.node_id not in covered_node_ids
        }
        supplemental = segment_document(
            extraction.document, include_node_ids=uncovered_node_ids
        )
        segments = resequence_segments(
            extraction.document, [*native_segments, *supplemental]
        )
    else:
        segments = segment_document(extraction.document)

    prefix = (
        f"source-content/sources/{job.source_id}/versions/{job.source_version_id}/"
        f"extractions/{job.job_id}"
    )
    warning_count = len(extraction.warnings)
    quality = evaluate_extraction(
        extraction.document,
        mapping_warnings=extraction.warnings,
        artifact_ids={artifact.artifact_id for artifact in extraction.artifacts},
    )
    original_filename = (
        "epub-original.json" if extension == "epub" else "docling-original.json"
    )
    payloads = {
        "document.json": extraction.document.model_dump_json(indent=2).encode(),
        original_filename: json.dumps(extraction.original, sort_keys=True).encode(),
        "report.json": quality.model_dump_json(indent=2).encode(),
        "segments.json": json.dumps(
            [segment.model_dump(mode="json") for segment in segments],
            indent=2,
            sort_keys=True,
        ).encode(),
    }
    entries = []
    for filename, body in payloads.items():
        key = f"{prefix}/{filename}"
        storage.put(key, body, "application/json")
        entries.append(
            ArtifactEntry(
                artifact_id=filename.removesuffix(".json"),
                kind=filename.removesuffix(".json").replace("-", "_"),
                object_key=key,
                sha256=hashlib.sha256(body).hexdigest(),
                content_type="application/json",
                size_bytes=len(body),
            )
        )
    for artifact in extraction.artifacts:
        key = f"{prefix}/{artifact.filename}"
        storage.put(key, artifact.body, artifact.content_type)
        entries.append(
            ArtifactEntry(
                artifact_id=artifact.artifact_id,
                kind=artifact.kind,
                object_key=key,
                sha256=hashlib.sha256(artifact.body).hexdigest(),
                content_type=artifact.content_type,
                size_bytes=len(artifact.body),
            )
        )
    manifest = ArtifactManifest(
        source_version_id=job.source_version_id,
        extraction_run_id=job.job_id,
        artifacts=entries,
    )
    manifest_key = f"{prefix}/artifact-manifest.json"
    storage.put(manifest_key, manifest.model_dump_json(indent=2).encode(), "application/json")
    _index_segments(extraction.document.source_version_id, segments)
    update_job_status(
        job.job_id,
        "ready",
        format_metadata={
            "format": extension,
            "node_count": len(extraction.document.nodes),
            "warning_count": warning_count,
            "chapter_count": extraction.document.chapter_count,
        },
        expected_status="processing",
        artifact_manifest_object_key=manifest_key,
    )


def _index_segments(source_version_id, segments, index=None):
    from .source_index import SourceSegmentIndex

    (index or SourceSegmentIndex()).replace(source_version_id, segments)


def _add_visual_explanations(extraction, service=None):
    from .ocr import extract_visible_text
    from .rendering import RenderedArtifact
    from .visual_explanations import VisualExplanationService, attach_visual_explanation

    document = extraction.document
    artifacts = list(extraction.artifacts)
    warnings = list(extraction.warnings)
    visual_nodes = [node for node in document.nodes if node.asset_id]
    if not visual_nodes:
        return extraction
    service = service or VisualExplanationService()
    for visual in visual_nodes:
        crop = next(
            (artifact for artifact in artifacts if artifact.kind == "picture_crop" and visual.node_id in artifact.artifact_id),
            None,
        )
        if crop is None:
            warnings.append(f"visual_crop_missing:{visual.node_id}")
            continue
        try:
            visible_text, _confidence = extract_visible_text(crop.body)
            explanation = service.explain(
                document=document,
                visual_node=visual,
                crop=crop,
                visible_text=visible_text,
            )
            document = attach_visual_explanation(document, explanation)
            artifacts.append(
                RenderedArtifact(
                    artifact_id=f"visual-explanation-{visual.node_id}",
                    kind="visual_explanation",
                    filename=f"visual-explanations/{visual.node_id}.json",
                    content_type="application/json",
                    body=explanation.model_dump_json(indent=2).encode(),
                )
            )
        except Exception as exc:
            logger.warning("Visual explanation failed for %s: %s", visual.node_id, exc)
            warnings.append(f"visual_explanation_failed:{visual.node_id}")
    return replace(extraction, document=document, artifacts=tuple(artifacts), warnings=tuple(warnings))


async def _main() -> None:
    from ..storage import get_storage
    from .repository import init_db, recover_stale_jobs

    logging.basicConfig(level=logging.INFO)
    init_db()
    recovered = recover_stale_jobs()
    if recovered:
        logger.info("[source-ingestion] Recovered %s stale run(s)", recovered)
    from src.source_authoring.job_repository import recover_stale_objective_jobs

    objective_recovered = recover_stale_objective_jobs()
    if objective_recovered:
        logger.info(
            "[source-authoring] Recovered %s stale objective job(s)",
            objective_recovered,
        )
    await background_worker(get_storage())


if __name__ == "__main__":
    asyncio.run(_main())
