"""Shared LiteLLM connection settings and purpose-specific model aliases."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterator, Mapping


BASE_URL_ENV = "LITE_LLM_BASE_URL"
API_KEY_ENV = "LITE_LLM_API_KEY"
DEFAULT_BASE_URL = "http://litellm:4000"
DEFAULT_API_KEY = "sk-local-dev"


@dataclass(frozen=True)
class LLMTelemetryContext:
    """Job-level identifiers inherited by nested LiteLLM calls."""

    job_id: str | None = None
    task_id: str | None = None


_telemetry_context: ContextVar[LLMTelemetryContext] = ContextVar(
    "llm_telemetry_context",
    default=LLMTelemetryContext(),
)


def _canonical_job_id(value: str | None) -> str | None:
    """Collapse internal planning/workflow prefixes to the UI-visible job ID."""

    if not value:
        return None
    for prefix in ("planning-", "workflow-"):
        if value.startswith(prefix) and len(value) > len(prefix):
            return value[len(prefix) :]
    return value


class ModelAlias(StrEnum):
    """Aliases that must have matching entries in ``litellm/config.yaml``."""

    CURRICULUM_ASSEMBLY = "curriculum-assembly"
    FORMAT_SELECTION = "format-selection"
    PODCAST_MODALITY_PLANNING = "podcast-modality-planning"
    VIDEO_MODALITY_PLANNING = "video-modality-planning"
    ELEARNING_MODALITY_PLANNING = "elearning-modality-planning"
    PODCAST_WORKFLOW_PLANNING = "podcast-workflow-planning"
    VIDEO_WORKFLOW_PLANNING = "video-workflow-planning"
    ELEARNING_WORKFLOW_PLANNING = "elearning-workflow-planning"
    ELEARNING_COURSE_AUTHORING = "elearning-course-authoring"
    ELEARNING_COURSE_REVIEW = "elearning-course-review"
    MANIM_SCENE_GENERATION = "manim-scene-generation"
    MANIM_SCENE_REPAIR = "manim-scene-repair"
    SLIDE_NEEDS_PLANNING = "slide-needs-planning"
    SLIDE_TEMPLATE_SELECTION = "slide-template-selection"
    SLIDE_CONTENT_FITTING = "slide-content-fitting"
    LEGACY_COURSE_VIDEO_GENERATION = "legacy-course-video-generation"
    COMMISSIONING_REQUEST_INTERPRETATION = "commissioning-request-interpretation"
    COMMISSIONING_CANDIDATE_CURATION = "commissioning-candidate-curation"
    COMMISSIONING_COURSE_ASSEMBLY = "commissioning-course-assembly"
    RLO_CATALOG_EMBEDDING = "rlo-catalog-embedding"
    COMPONENT_CATALOG_EMBEDDING = "component-catalog-embedding"
    SLIDE_IMAGE_GENERATION = "slide-image-generation"
    PODCAST_SPEECH_SYNTHESIS = "podcast-speech-synthesis"
    MANIM_SPEECH_SYNTHESIS = "manim-speech-synthesis"
    SOURCE_VISUAL_EXPLANATION = "source-visual-explanation"
    SOURCE_SEGMENT_EMBEDDING = "source-segment-embedding"
    SOURCE_SECTION_MAPPING = "source-section-mapping"
    SOURCE_DOCUMENT_SYNTHESIS = "source-document-synthesis"
    SOURCE_PRACTITIONER_LENS = "source-practitioner-lens"
    SOURCE_OBJECTIVE_PROPOSAL = "source-objective-proposal"
    SOURCE_RELATED_OBJECTIVE_DISCOVERY = "source-related-objective-discovery"
    SOURCE_OBJECTIVE_EVIDENCE_VERIFICATION = "source-objective-evidence-verification"
    SOURCE_OBJECTIVE_PEDAGOGY_CRITIQUE = "source-objective-pedagogy-critique"
    SOURCE_RLO_DRAFTING = "source-rlo-drafting"
    SOURCE_RLO_DOMAIN_ENRICHMENT = "source-rlo-domain-enrichment"
    SOURCE_RLO_GROUNDING_REVIEW = "source-rlo-grounding-review"
    SOURCE_RLO_PEDAGOGY_REVIEW = "source-rlo-pedagogy-review"


@dataclass(frozen=True)
class LiteLLMSettings:
    base_url: str
    api_key: str


@contextmanager
def llm_telemetry_context(
    *,
    job_id: str | None = None,
    task_id: str | None = None,
) -> Iterator[None]:
    """Attach workflow identifiers to every LiteLLM call in this context."""

    current = _telemetry_context.get()
    token = _telemetry_context.set(
        LLMTelemetryContext(
            job_id=_canonical_job_id(job_id) or current.job_id,
            task_id=task_id or current.task_id,
        )
    )
    try:
        yield
    finally:
        _telemetry_context.reset(token)


def build_litellm_metadata(
    model_alias: str | ModelAlias,
    *,
    operation: str | None = None,
    job_id: str | None = None,
    task_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build LiteLLM metadata with Langfuse's recognized semantic fields."""

    context = _telemetry_context.get()
    resolved_job_id = _canonical_job_id(job_id) or context.job_id
    resolved_task_id = task_id or context.task_id
    alias = str(model_alias)
    generation_name = f"{alias}.{operation}" if operation else alias
    metadata: dict[str, Any] = {
        "generation_name": generation_name,
        "model_alias": alias,
        "tags": ["omnichannel-learning", alias],
    }
    if operation:
        metadata["operation"] = operation
    if resolved_job_id:
        metadata.update(
            {
                "trace_id": hashlib.sha256(resolved_job_id.encode("utf-8")).hexdigest()[:32],
                "trace_name": f"learning-job:{resolved_job_id}",
                "session_id": resolved_job_id,
                "job_id": resolved_job_id,
                "workflow_id": resolved_job_id,
            }
        )
    if resolved_task_id:
        metadata["task_id"] = resolved_task_id
    reserved = {
        "generation_name",
        "model_alias",
        "tags",
        "operation",
        "trace_id",
        "trace_name",
        "session_id",
        "job_id",
        "workflow_id",
        "task_id",
    }
    for key, value in (attributes or {}).items():
        if key not in reserved and value is not None:
            metadata[key] = value
    return metadata


def build_langfuse_headers(
    model_alias: str | ModelAlias,
    *,
    operation: str | None = None,
    job_id: str | None = None,
    task_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Promote safe request metadata through LiteLLM's Langfuse OTEL proxy."""
    metadata = build_litellm_metadata(
        model_alias,
        operation=operation,
        job_id=job_id,
        task_id=task_id,
        attributes=attributes,
    )
    headers = {
        "langfuse_generation_name": str(metadata["generation_name"]),
        "langfuse_tags": json.dumps(metadata["tags"]),
    }
    for metadata_key, header_key in (
        ("session_id", "langfuse_session_id"),
        ("trace_name", "langfuse_trace_name"),
        ("trace_id", "langfuse_trace_id"),
    ):
        value = metadata.get(metadata_key)
        if value:
            headers[header_key] = str(value)
    trace_metadata = {
        key: value
        for key, value in metadata.items()
        if key
        not in {
            "generation_name",
            "tags",
            "session_id",
            "trace_name",
            "trace_id",
        }
    }
    headers["langfuse_trace_metadata"] = json.dumps(
        trace_metadata, separators=(",", ": "), sort_keys=True
    )
    return headers


def load_lite_llm_settings(
    *,
    required: bool = True,
    environ: Mapping[str, str] | None = None,
) -> LiteLLMSettings:
    """Load the one application-wide LiteLLM connection."""

    values = os.environ if environ is None else environ
    base_url = values.get(BASE_URL_ENV, "").strip()
    api_key = values.get(API_KEY_ENV, "").strip()
    if required and not base_url:
        raise ValueError(f"{BASE_URL_ENV} is required")
    if required and not api_key:
        raise ValueError(f"{API_KEY_ENV} is required")
    return LiteLLMSettings(
        base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
        api_key=api_key or DEFAULT_API_KEY,
    )


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "DEFAULT_API_KEY",
    "DEFAULT_BASE_URL",
    "LiteLLMSettings",
    "LLMTelemetryContext",
    "ModelAlias",
    "build_litellm_metadata",
    "build_langfuse_headers",
    "llm_telemetry_context",
    "load_lite_llm_settings",
]
