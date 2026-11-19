"""Guardrails for the application-wide LiteLLM configuration."""

import hashlib
from pathlib import Path

import yaml

from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    llm_telemetry_context,
    load_lite_llm_settings,
)


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_application_alias_is_declared_once_in_litellm_config() -> None:
    config = yaml.safe_load((_REPO_ROOT / "litellm" / "config.yaml").read_text())
    configured = [entry["model_name"] for entry in config["model_list"]]
    application_aliases = {str(alias) for alias in ModelAlias}

    assert len(configured) == len(set(configured))
    assert application_aliases <= set(configured)


def test_reasoning_defaults_are_scoped_by_model_function() -> None:
    config = yaml.safe_load((_REPO_ROOT / "litellm" / "config.yaml").read_text())
    reasoning_defaults = {
        entry["model_name"]: entry["litellm_params"].get("reasoning_effort")
        for entry in config["model_list"]
        if "reasoning_effort" in entry["litellm_params"]
    }

    assert reasoning_defaults == {
        str(ModelAlias.FORMAT_SELECTION): "medium",
        str(ModelAlias.ELEARNING_COURSE_AUTHORING): "low",
        str(ModelAlias.ELEARNING_COURSE_REVIEW): "medium",
        str(ModelAlias.MANIM_SCENE_REPAIR): "low",
        str(ModelAlias.SLIDE_CONTENT_FITTING): "medium",
        str(ModelAlias.COMMISSIONING_CANDIDATE_CURATION): "low",
        str(ModelAlias.SOURCE_OBJECTIVE_PROPOSAL): "low",
        str(ModelAlias.SOURCE_RELATED_OBJECTIVE_DISCOVERY): "low",
        str(ModelAlias.SOURCE_OBJECTIVE_EVIDENCE_VERIFICATION): "low",
        str(ModelAlias.SOURCE_OBJECTIVE_PEDAGOGY_CRITIQUE): "low",
        str(ModelAlias.SOURCE_RLO_DRAFTING): "low",
        str(ModelAlias.SOURCE_RLO_DOMAIN_ENRICHMENT): "low",
        str(ModelAlias.SOURCE_RLO_GROUNDING_REVIEW): "low",
        str(ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW): "low",
    }


def test_model_routes_match_task_complexity() -> None:
    config = yaml.safe_load((_REPO_ROOT / "litellm" / "config.yaml").read_text())
    routes = {
        entry["model_name"]: entry["litellm_params"]["model"]
        for entry in config["model_list"]
    }

    assert routes[str(ModelAlias.ELEARNING_COURSE_REVIEW)] == "openai/gpt-5.5"
    for alias in (
        ModelAlias.COMMISSIONING_REQUEST_INTERPRETATION,
        ModelAlias.SLIDE_NEEDS_PLANNING,
        ModelAlias.SLIDE_TEMPLATE_SELECTION,
        ModelAlias.SOURCE_VISUAL_EXPLANATION,
        ModelAlias.SOURCE_SECTION_MAPPING,
        ModelAlias.SOURCE_DOCUMENT_SYNTHESIS,
        ModelAlias.SOURCE_PRACTITIONER_LENS,
    ):
        assert routes[str(alias)] == "openai/gpt-5.6-luna"

    for alias in (
        ModelAlias.SOURCE_OBJECTIVE_PROPOSAL,
        ModelAlias.SOURCE_RELATED_OBJECTIVE_DISCOVERY,
        ModelAlias.SOURCE_OBJECTIVE_EVIDENCE_VERIFICATION,
        ModelAlias.SOURCE_OBJECTIVE_PEDAGOGY_CRITIQUE,
        ModelAlias.SOURCE_RLO_DRAFTING,
        ModelAlias.SOURCE_RLO_DOMAIN_ENRICHMENT,
        ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
    ):
        assert routes[str(alias)] == "openai/gpt-5.6-terra"

    assert (
        routes[str(ModelAlias.SOURCE_RLO_PEDAGOGY_REVIEW)]
        == "openai/gpt-5.6-sol"
    )

    non_sol_aliases = {
        ModelAlias.ELEARNING_COURSE_REVIEW,
        ModelAlias.COMMISSIONING_REQUEST_INTERPRETATION,
        ModelAlias.SLIDE_NEEDS_PLANNING,
        ModelAlias.SLIDE_TEMPLATE_SELECTION,
        ModelAlias.SOURCE_VISUAL_EXPLANATION,
        ModelAlias.SOURCE_SECTION_MAPPING,
        ModelAlias.SOURCE_DOCUMENT_SYNTHESIS,
        ModelAlias.SOURCE_PRACTITIONER_LENS,
        ModelAlias.SOURCE_OBJECTIVE_PROPOSAL,
        ModelAlias.SOURCE_RELATED_OBJECTIVE_DISCOVERY,
        ModelAlias.SOURCE_OBJECTIVE_EVIDENCE_VERIFICATION,
        ModelAlias.SOURCE_OBJECTIVE_PEDAGOGY_CRITIQUE,
        ModelAlias.SOURCE_RLO_DRAFTING,
        ModelAlias.SOURCE_RLO_DOMAIN_ENRICHMENT,
        ModelAlias.SOURCE_RLO_GROUNDING_REVIEW,
        ModelAlias.SOURCE_SEGMENT_EMBEDDING,
        ModelAlias.RLO_CATALOG_EMBEDDING,
        ModelAlias.COMPONENT_CATALOG_EMBEDDING,
        ModelAlias.SLIDE_IMAGE_GENERATION,
        ModelAlias.PODCAST_SPEECH_SYNTHESIS,
        ModelAlias.MANIM_SPEECH_SYNTHESIS,
    }
    for alias in set(ModelAlias) - non_sol_aliases:
        assert routes[str(alias)] == "openai/gpt-5.6-sol"


def test_litellm_exports_all_gateway_calls_to_langfuse() -> None:
    config = yaml.safe_load((_REPO_ROOT / "litellm" / "config.yaml").read_text())

    assert config["litellm_settings"]["callbacks"] == ["langfuse_otel"]


def test_litellm_bounds_provider_timeout_and_retry_count() -> None:
    config = yaml.safe_load((_REPO_ROOT / "litellm" / "config.yaml").read_text())

    assert config["router_settings"]["timeout"] == 600
    assert config["router_settings"]["num_retries"] == 1


def test_shared_connection_uses_only_canonical_environment_names() -> None:
    settings = load_lite_llm_settings(
        environ={
            "LITE_LLM_BASE_URL": "http://gateway.example/v1/",
            "LITE_LLM_API_KEY": "shared-key",
            "LITELLM_BASE_URL": "http://legacy.example",
            "OPENAI_API_KEY": "provider-key",
        }
    )

    assert settings.base_url == "http://gateway.example/v1"
    assert settings.api_key == "shared-key"


def test_langfuse_metadata_groups_function_calls_by_ui_job() -> None:
    job_id = "assembly-123"
    with llm_telemetry_context(
        job_id=f"workflow-{job_id}",
        task_id="elearning-course-author",
    ):
        metadata = build_litellm_metadata(
            ModelAlias.ELEARNING_COURSE_AUTHORING,
            operation="review",
        )

    assert metadata["generation_name"] == "elearning-course-authoring.review"
    assert metadata["model_alias"] == "elearning-course-authoring"
    assert metadata["job_id"] == job_id
    assert metadata["session_id"] == job_id
    assert metadata["task_id"] == "elearning-course-author"
    assert metadata["trace_id"] == hashlib.sha256(job_id.encode()).hexdigest()[:32]
    assert "job_id" not in build_litellm_metadata(ModelAlias.FORMAT_SELECTION)


def test_langfuse_metadata_accepts_non_sensitive_operation_attributes() -> None:
    metadata = build_litellm_metadata(
        ModelAlias.ELEARNING_COURSE_AUTHORING,
        operation="patch",
        attributes={
            "screen_count": 2,
            "screen_families": "title,completion",
            "finding_codes": "LEARNER_INSTRUCTION_UNUSABLE",
            "repair_outcome": "requested",
        },
    )

    assert metadata["screen_count"] == 2
    assert metadata["screen_families"] == "title,completion"
    assert metadata["finding_codes"] == "LEARNER_INSTRUCTION_UNUSABLE"
    assert metadata["repair_outcome"] == "requested"


def test_langfuse_proxy_headers_promote_job_and_function_fields() -> None:
    with llm_telemetry_context(job_id="workflow-assembly-123", task_id="author-1"):
        headers = build_langfuse_headers(
            ModelAlias.ELEARNING_COURSE_AUTHORING,
            operation="review",
            attributes={"screen_count": 6},
        )

    assert headers["langfuse_generation_name"] == "elearning-course-authoring.review"
    assert headers["langfuse_session_id"] == "assembly-123"
    assert headers["langfuse_trace_name"] == "learning-job:assembly-123"
    assert len(headers["langfuse_trace_id"]) == 32
    assert '"task_id": "author-1"' in headers["langfuse_trace_metadata"]
    assert '"screen_count": 6' in headers["langfuse_trace_metadata"]
