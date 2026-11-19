"""
Tests for ToolManifest and ProductionToolDefinition.

Verifies that manifests are serializable, that schemas derive from typed
input/output models, and that planner-visible manifests contain no
executor instances, credentials, or provider configuration.
"""
from __future__ import annotations

import json

import pytest

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest
from learning_pipeline.tools.speech.contracts import SpeechSynthesisInput, SpeechSynthesisOutput
from learning_pipeline.tools.speech.definition import speech_tool_definition


def test_speech_manifest_is_serializable() -> None:
    defn = speech_tool_definition()
    data = defn.manifest.model_dump()
    # Must round-trip through JSON without error
    restored = json.loads(json.dumps(data))
    assert restored["capability"] == "speech.synthesize"


def test_speech_manifest_task_type() -> None:
    manifest = speech_tool_definition().manifest
    assert manifest.task_type == "speech.synthesize"


def test_speech_manifest_contract_version() -> None:
    manifest = speech_tool_definition().manifest
    assert manifest.contract_version == "1.0"


def test_speech_manifest_supported_modalities_includes_podcast() -> None:
    manifest = speech_tool_definition().manifest
    assert Modality.PODCAST in manifest.supported_modalities


def test_speech_manifest_input_schema_derived_from_typed_model() -> None:
    manifest = speech_tool_definition().manifest
    canonical = SpeechSynthesisInput.model_json_schema()
    assert manifest.input_schema == canonical


def test_speech_manifest_output_schema_derived_from_typed_model() -> None:
    manifest = speech_tool_definition().manifest
    canonical = SpeechSynthesisOutput.model_json_schema()
    assert manifest.output_schema == canonical


def test_speech_manifest_input_schema_contains_required_fields() -> None:
    schema = speech_tool_definition().manifest.input_schema
    # All three required fields appear in the schema properties
    props = schema.get("properties", {})
    assert "text" in props
    assert "speaker" in props
    assert "line_id" in props


def test_speech_manifest_output_schema_contains_audio_uri() -> None:
    schema = speech_tool_definition().manifest.output_schema
    props = schema.get("properties", {})
    assert "audio_uri" in props
    assert "usage" in props


def test_manifest_contains_no_executor() -> None:
    defn = speech_tool_definition()
    # ProductionToolDefinition explicitly stores no executor
    assert not hasattr(defn, "executor")
    dumped = defn.manifest.model_dump()
    # The serialised manifest should have no key that looks like an executor
    assert "executor" not in dumped
    assert "client" not in dumped


def test_manifest_contains_no_credentials() -> None:
    dumped = speech_tool_definition().manifest.model_dump()
    text = json.dumps(dumped).lower()
    # Check for actual credential field names — not "token" which appears legitimately
    # in usage field names like "input_tokens_estimate".
    for keyword in ("api_key", "password", "secret", "bearer", "base_url"):
        assert keyword not in text, f"Credential keyword {keyword!r} found in manifest"


def test_production_tool_definition_binds_correct_models() -> None:
    defn = speech_tool_definition()
    assert defn.input_model is SpeechSynthesisInput
    assert defn.output_model is SpeechSynthesisOutput
