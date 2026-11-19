"""
Tests for runtime mode selection: fake vs real executor registry.

Verifies that:
- Fake mode never requires credentials.
- Fake mode registers executors for all known task types.
- Real mode requires TtsSettings (MissingRealModeConfigError without them).
- Same task type contracts apply in both modes.
- The reference BuildPlan works unchanged in fake mode (unchanged fixture check).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_pipeline.config import (
    REGISTERED_TASK_TYPES,
    TtsSettings,
    build_fake_registry,
    build_tool_catalog,
)
from learning_pipeline.runtime.execution import ExecutorRegistry
from learning_pipeline.tools.errors import MissingRealModeConfigError


# ── Fake mode ─────────────────────────────────────────────────────────────────


def test_fake_registry_requires_no_credentials() -> None:
    """build_fake_registry must succeed without any environment variables."""
    registry = build_fake_registry()
    assert isinstance(registry, ExecutorRegistry)


def test_fake_registry_covers_non_elearning_task_types() -> None:
    """build_fake_registry covers podcast/video task types.

    E-learning task types are excluded because the assembler requires a
    FileArtifactStore.  Use build_elearning_reference_registry() for those.
    """
    from learning_pipeline.config import ELEARNING_TASK_TYPES

    registry = build_fake_registry()
    non_elearning = REGISTERED_TASK_TYPES - ELEARNING_TASK_TYPES
    for task_type in non_elearning:
        executor = registry.get(task_type)
        assert executor is not None, f"No fake executor for task type {task_type!r}"


def test_elearning_reference_registry_covers_all_elearning_task_types(tmp_path) -> None:
    """build_elearning_reference_registry covers all six catalog task types."""
    from learning_pipeline.config import ELEARNING_TASK_TYPES, build_elearning_reference_registry

    registry = build_elearning_reference_registry(tmp_path / "artifacts")
    for task_type in REGISTERED_TASK_TYPES:
        executor = registry.get(task_type)
        assert executor is not None, f"No executor for task type {task_type!r}"


async def test_fake_speech_executor_returns_audio_uri() -> None:
    from learning_pipeline.runtime.execution import ExecutionContext

    registry = build_fake_registry()
    executor = registry.get("speech.synthesize")
    ctx = ExecutionContext(
        workflow_id="wf-rt-test",
        task_id="seg-1",
        attempt=1,
        inputs={
            "text": "Hello world",
            "speaker": "Host",
            "line_id": "l-01",
        },
    )
    result = await executor.execute(ctx)
    assert "audio_uri" in result


# ── Real mode error paths ─────────────────────────────────────────────────────


def test_real_mode_missing_env_vars_raises(monkeypatch) -> None:
    """load_tts_settings() must raise when required env vars are missing."""
    from learning_pipeline.config import load_tts_settings

    monkeypatch.delenv("LITE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITE_LLM_API_KEY", raising=False)
    with pytest.raises(MissingRealModeConfigError, match="LITE_LLM_BASE_URL"):
        load_tts_settings()


def test_real_mode_missing_api_key_raises(monkeypatch) -> None:
    from learning_pipeline.config import load_tts_settings

    monkeypatch.setenv("LITE_LLM_BASE_URL", "http://localhost:4000")
    monkeypatch.delenv("LITE_LLM_API_KEY", raising=False)
    with pytest.raises(MissingRealModeConfigError, match="LITE_LLM_API_KEY"):
        load_tts_settings()


# ── Real mode registry structure ──────────────────────────────────────────────


def _fake_tts_settings(tmp_path: Path) -> TtsSettings:
    return TtsSettings(
        litellm_base_url="http://fake-tts:4000",
        litellm_api_key="fake-key",
        model="gemini-tts",
        host_voice="Aoede",
        expert_voice="Charon",
        input_cost_per_token=0.000001,
        output_cost_per_token=0.00002,
        artifact_store_root=tmp_path / "artifacts",
    )


def test_real_registry_has_speech_executor(tmp_path) -> None:
    from learning_pipeline.config import build_real_registry

    registry = build_real_registry(settings=_fake_tts_settings(tmp_path))
    executor = registry.get("speech.synthesize")
    assert executor is not None


def test_real_registry_speech_executor_is_real_type(tmp_path) -> None:
    from learning_pipeline.config import build_real_registry
    from learning_pipeline.tools.speech.executor import RealSpeechExecutor

    registry = build_real_registry(settings=_fake_tts_settings(tmp_path))
    executor = registry.get("speech.synthesize")
    assert isinstance(executor, RealSpeechExecutor)


def test_real_registry_also_covers_audio_assemble(tmp_path) -> None:
    from learning_pipeline.config import build_real_registry

    registry = build_real_registry(settings=_fake_tts_settings(tmp_path))
    assert registry.get("audio.assemble") is not None


def test_real_registry_assembly_executor_is_real_type(tmp_path) -> None:
    from learning_pipeline.config import build_real_registry
    from learning_pipeline.tools.audio_assembly.executor import RealAudioAssemblyExecutor

    registry = build_real_registry(settings=_fake_tts_settings(tmp_path))
    executor = registry.get("audio.assemble")
    assert isinstance(executor, RealAudioAssemblyExecutor)


def test_real_podcast_registry_contains_no_fake_fallback_capabilities(tmp_path) -> None:
    from learning_pipeline.config import build_real_registry

    registry = build_real_registry(settings=_fake_tts_settings(tmp_path))
    assert registry.registered_task_types == frozenset(
        {"speech.synthesize", "audio.assemble"}
    )


# ── Contract parity ───────────────────────────────────────────────────────────


def test_speech_input_contract_is_same_in_both_modes() -> None:
    """The input_model for speech.synthesize must be the same type in fake and real modes."""
    from learning_pipeline.tools.speech.contracts import SpeechSynthesisInput

    catalog = build_tool_catalog()
    defn = catalog.resolve_capability("speech.synthesize")
    assert defn.input_model is SpeechSynthesisInput


def test_speech_output_contract_is_same_in_both_modes() -> None:
    from learning_pipeline.tools.speech.contracts import SpeechSynthesisOutput

    catalog = build_tool_catalog()
    defn = catalog.resolve_capability("speech.synthesize")
    assert defn.output_model is SpeechSynthesisOutput


# ── Reference fixture unchanged ───────────────────────────────────────────────

_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "examples"
    / "reference"
    / "podcast"
    / "build_plan.json"
)


def test_reference_build_plan_task_types_all_registered() -> None:
    """All task_type values in the reference fixture must be in REGISTERED_TASK_TYPES."""
    data = json.loads(_FIXTURE_PATH.read_text())
    for task in data["tasks"]:
        assert task["task_type"] in REGISTERED_TASK_TYPES, (
            f"task_type {task['task_type']!r} is not registered"
        )


def test_reference_build_plan_speech_inputs_use_audio_uri_output_key() -> None:
    """Speech tasks must declare audio_uri in output_keys (migrated from audio_file)."""
    data = json.loads(_FIXTURE_PATH.read_text())
    speech_tasks = [t for t in data["tasks"] if t["task_type"] == "speech.synthesize"]
    assert speech_tasks, "No speech.synthesize tasks found in reference fixture"
    for task in speech_tasks:
        assert "audio_uri" in task["output_keys"], (
            f"Task {task['task_id']} missing audio_uri in output_keys"
        )


def test_reference_build_plan_loads_in_fake_mode(tmp_path) -> None:
    """The reference BuildPlan must parse and validate without error in fake mode."""
    import json as _json

    from learning_pipeline.contracts.execution import BuildPlan
    from learning_pipeline.validation.build_plan import validate_build_plan

    data = _json.loads(_FIXTURE_PATH.read_text())
    plan = BuildPlan.model_validate(data)
    validate_build_plan(plan, REGISTERED_TASK_TYPES)  # must not raise
