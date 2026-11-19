"""Tests for ManimGenerationController — the bounded agentic state machine.

No Docker, no LLM, no TTS, no Manim calls.  All providers are replaced with
fake implementations that are configurable per-test.

Test coverage:
 1. Success via template path (vertical_stack draft)
 2. Success via generated-source path (free-form draft)
 3. Completed checkpoint reuse returns immediately (no LLM/render call)
 4. Draft checkpoint reuse skips LLM call but still renders
 5. Infrastructure error retries without LLM call
 6. Source error triggers LLM repair (repair_draft used)
 7. Repair budget exhausted → ManimRepairBudgetError
 8. Model call limit → ManimPolicyError on render repair
 9. Cost limit → ManimPolicyError
10. Invalid MP4 header → ManimMediaValidationError
11. Source policy violation → ManimSourcePolicyError (caught before render)
12. Max infrastructure failures → ManimInfrastructureError
13. Idempotency key differs when brief changes
14. Full idempotent: second call returns cached output (no additional calls)
"""
from __future__ import annotations

import hashlib
import json
import pytest

from learning_pipeline.media_validation import read_mp4_dimensions
from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.elearning_bundle.contracts import AnimationBrief, ManimVideoOutput
from learning_pipeline.tools.manim_video._contracts import (
    ManimInfrastructureError,
    ManimMediaValidationError,
    ManimPolicyError,
    ManimRenderPolicy,
    ManimRepairBudgetError,
    ManimSourcePolicyError,
)
from learning_pipeline.tools.manim_video._controller import ManimGenerationController
from learning_pipeline.tools.manim_video._manim_client import (
    FakeManimLLMClient,
    ManimSceneDraft,
    _default_fake_draft,
    _free_form_fake_draft,
)
from learning_pipeline.tools.manim_video._render_runner import (
    FakeManimRenderRunner,
    _FAKE_MP4_BYTES,
)
from learning_pipeline.tools.manim_video._source_policy import SourcePolicyValidator
from learning_pipeline.tools.manim_video._template_catalog import ManimTemplateCatalog


# ── Shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return FileArtifactStore(tmp_path / "artifacts")


def _brief(
    animation_id: str = "intro-animation",
    narration: str | None = "This is the narration.",
    voice_profile: str | None = "default",
) -> AnimationBrief:
    return AnimationBrief(
        animation_id=animation_id,
        source_scene_ids=("scene-intro",),
        learning_objective="Understand ADKAR.",
        teaching_purpose="Introduction.",
        visual_direction="vertical_stack",
        narration_script=narration,
        voice_profile=voice_profile,
        resolved_context_uri="fake://ctx/test.json",
        resolved_context_sha256="a" * 64,
    )


def _controller(
    store,
    *,
    llm_client=None,
    runner=None,
    policy=None,
    render_policy=None,
) -> ManimGenerationController:
    return ManimGenerationController(
        artifact_store=store,
        llm_client=llm_client or FakeManimLLMClient(),
        render_runner=runner or FakeManimRenderRunner(),
        template_catalog=ManimTemplateCatalog(),
        source_validator=SourcePolicyValidator(),
        tts_import="from tts_service import LiteLLMTTSService",
        tts_service_call='LiteLLMTTSService(voice="Kore", model="manim-speech-synthesis")',
        policy=policy or AgenticExecutionPolicy(max_model_calls=5, max_repair_attempts=2),
        render_policy=render_policy or ManimRenderPolicy(max_render_attempts=3),
    )


_CTX_BYTES = b"{}"
_CTX_HASH = hashlib.sha256(_CTX_BYTES).hexdigest()


async def _run(ctrl: ManimGenerationController, brief: AnimationBrief = None) -> ManimVideoOutput:
    if brief is None:
        brief = _brief()
    return await ctrl.run(
        brief,
        workflow_id="wf-test",
        task_id="task-1",
        context_bytes=_CTX_BYTES,
        context_hash=_CTX_HASH,
    )


# ── 1: Success via template path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_template_path(store):
    ctrl = _controller(store)
    output = await _run(ctrl)
    assert isinstance(output, ManimVideoOutput)
    assert output.video.uri.endswith(".mp4")
    assert output.video_uri == output.video.uri


@pytest.mark.asyncio
async def test_standard_profile_requests_720p_media(store):
    class CapturingRunner(FakeManimRenderRunner):
        request = None

        async def render(self, request):
            self.request = request
            return await super().render(request)

    runner = CapturingRunner()
    ctrl = _controller(store, runner=runner)
    await _run(ctrl)

    assert runner.request.quality == "medium_quality"
    assert read_mp4_dimensions(_FAKE_MP4_BYTES) == (1280, 720)


@pytest.mark.asyncio
async def test_draft_payload_lists_entire_template_catalog(store):
    """The agent must see EVERY registered template — a truncated list is what
    silently pushed sequence visuals to free-form source."""
    from learning_pipeline.tools.manim_video._manim_bridge import REGISTRY

    llm = FakeManimLLMClient()
    ctrl = _controller(store, llm_client=llm)
    await _run(ctrl)

    offered = llm.last_payload["available_templates"]
    assert {t["template_id"] for t in offered} == set(REGISTRY)
    for entry in offered:
        assert entry["description"]
        assert entry["min_items"] <= entry["max_items"]


# ── 2: Success via generated-source path ─────────────────────────────────────


@pytest.mark.asyncio
async def test_success_generated_source_path(store):
    draft = _free_form_fake_draft("intro-animation")
    ctrl = _controller(store, llm_client=FakeManimLLMClient(draft=draft))
    output = await _run(ctrl)
    assert output.generated_source is not None


def test_generated_source_receives_litellm_voiceover_service(store):
    ctrl = _controller(store)
    source = _free_form_fake_draft("intro-animation").generated_source

    prepared = ctrl._inject_voiceover_service(source)

    assert "from tts_service import LiteLLMTTSService" in prepared
    assert "self.set_speech_service(" in prepared
    assert "with self.voiceover(" in prepared


@pytest.mark.asyncio
async def test_success_without_audio_stream_is_repaired_then_rejected(store):
    class _SilentRunner:
        async def render(self, request):
            from learning_pipeline.tools.manim_video._contracts import ManimRenderResult
            return ManimRenderResult(
                status="success",
                video_bytes=_FAKE_MP4_BYTES,
                log_bytes=b"silent",
                has_audio=False,
            )

    ctrl = _controller(
        store,
        runner=_SilentRunner(),
        policy=AgenticExecutionPolicy(max_model_calls=2, max_repair_attempts=1),
        render_policy=ManimRenderPolicy(max_render_attempts=2),
    )

    with pytest.raises(ManimRepairBudgetError, match="no verified audio stream"):
        await _run(ctrl)


# ── 3: Completed checkpoint reuse ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completed_checkpoint_reuse(store):
    runner = FakeManimRenderRunner()
    llm = FakeManimLLMClient()
    ctrl = _controller(store, llm_client=llm, runner=runner)

    output1 = await _run(ctrl)
    call_count_after_1 = runner.call_count
    llm_calls_after_1 = llm.call_count

    output2 = await _run(ctrl)
    # No additional LLM or render calls on second invocation.
    assert runner.call_count == call_count_after_1
    assert llm.call_count == llm_calls_after_1
    assert output2.video_uri == output1.video_uri


# ── 4: Draft checkpoint reuse (skips LLM call) ───────────────────────────────


@pytest.mark.asyncio
async def test_draft_checkpoint_reuse(store):
    llm = FakeManimLLMClient()
    runner = FakeManimRenderRunner()
    ctrl = _controller(store, llm_client=llm, runner=runner)

    # Prime the checkpoint by running once, then clear just the completed checkpoint.
    await _run(ctrl)
    llm_calls_first = llm.call_count

    # Second run should reuse the completed checkpoint, no LLM call.
    await _run(ctrl)
    assert llm.call_count == llm_calls_first


# ── 5: Infrastructure error retries without LLM call ─────────────────────────


@pytest.mark.asyncio
async def test_infrastructure_error_retries_without_llm(store):
    runner = FakeManimRenderRunner(fail_attempts=2, fail_category="infrastructure_error")
    llm = FakeManimLLMClient()
    ctrl = _controller(store, llm_client=llm, runner=runner)

    output = await _run(ctrl)
    assert output.video_uri is not None
    # LLM called once for draft; zero repair calls (infra error never triggers repair).
    assert llm.call_count == 1


# ── 6: Source error triggers LLM repair ──────────────────────────────────────


@pytest.mark.asyncio
async def test_source_error_triggers_llm_repair(store):
    repair_draft = _free_form_fake_draft("intro-animation")
    runner = FakeManimRenderRunner(fail_attempts=1, fail_category="source_error")
    llm = FakeManimLLMClient(repair_draft=repair_draft)
    ctrl = _controller(store, llm_client=llm, runner=runner)

    output = await _run(ctrl)
    assert output.video_uri is not None
    assert llm.call_count >= 2  # initial draft + 1 repair


@pytest.mark.asyncio
async def test_geometry_validation_error_triggers_llm_repair(store):
    """The container's pre-render geometry gate fails with
    failure_category="geometry_validation_error"; the controller must route it
    through bounded LLM repair like any source defect, and the measured
    violations must reach the repair payload."""
    repair_draft = _free_form_fake_draft("intro-animation")
    runner = FakeManimRenderRunner(
        fail_attempts=1, fail_category="geometry_validation_error"
    )
    llm = FakeManimLLMClient(repair_draft=repair_draft)
    ctrl = _controller(store, llm_client=llm, runner=runner)

    output = await _run(ctrl)
    assert output.video_uri is not None
    assert llm.call_count >= 2  # initial draft + 1 repair
    assert llm.last_payload is not None
    assert llm.last_payload.get("repair_mode") is True
    assert "geometry_validation_error" in llm.last_payload.get("failure_message", "")
    assert llm.last_payload.get("repair_attempt_number") == 1


@pytest.mark.asyncio
async def test_final_geometry_repair_requests_simpler_composition(store):
    """The final bounded repair should change strategy instead of repeatedly
    asking the model to make the same local adjustment."""
    repair_draft = _free_form_fake_draft("intro-animation")
    runner = FakeManimRenderRunner(
        fail_attempts=2, fail_category="geometry_validation_error"
    )
    llm = FakeManimLLMClient(repair_draft=repair_draft)
    ctrl = _controller(store, llm_client=llm, runner=runner)

    output = await _run(ctrl)

    assert output.video_uri is not None
    assert llm.last_payload is not None
    assert llm.last_payload.get("repair_attempt_number") == 2
    assert "simplify" in llm.last_payload.get("repair_strategy", "").lower()


# ── 8: Repair budget exhausted ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repair_budget_exhausted(store):
    # Source error never resolves — always fails.
    runner = FakeManimRenderRunner(fail_attempts=999, fail_category="source_error")
    llm = FakeManimLLMClient()
    policy = AgenticExecutionPolicy(max_model_calls=5, max_repair_attempts=2)
    render_policy = ManimRenderPolicy(max_render_attempts=5)
    ctrl = _controller(store, llm_client=llm, runner=runner, policy=policy, render_policy=render_policy)

    with pytest.raises(ManimRepairBudgetError):
        await _run(ctrl)


# ── 9: Model call limit during repair ────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_call_limit_during_repair(store):
    runner = FakeManimRenderRunner(fail_attempts=999, fail_category="source_error")
    llm = FakeManimLLMClient()
    # max_model_calls=1: initial draft consumes it; no budget for repair.
    policy = AgenticExecutionPolicy(max_model_calls=1, max_repair_attempts=2)
    ctrl = _controller(store, llm_client=llm, runner=runner, policy=policy)

    with pytest.raises((ManimPolicyError, ManimRepairBudgetError)):
        await _run(ctrl)


# ── 10: Invalid MP4 header raises ManimMediaValidationError ──────────────────


@pytest.mark.asyncio
async def test_invalid_mp4_header_raises(store):
    class _BadMp4Runner:
        async def render(self, request):
            from learning_pipeline.tools.manim_video._contracts import ManimRenderResult
            return ManimRenderResult(
                status="success",
                video_bytes=b"not a valid mp4 header",
                log_bytes=b"ok",
                has_audio=True,
            )

    ctrl = _controller(store, runner=_BadMp4Runner())
    with pytest.raises(ManimMediaValidationError, match="ftyp"):
        await _run(ctrl)


# ── 11: Max infrastructure failures → ManimInfrastructureError ───────────────


@pytest.mark.asyncio
async def test_max_infrastructure_failures_raises(store):
    runner = FakeManimRenderRunner(fail_attempts=999, fail_category="infrastructure_error")
    render_policy = ManimRenderPolicy(max_render_attempts=3)
    ctrl = _controller(store, runner=runner, render_policy=render_policy)

    with pytest.raises(ManimInfrastructureError):
        await _run(ctrl)


# ── 12: Source policy violation raised before render ─────────────────────────


@pytest.mark.asyncio
async def test_source_policy_violation_raised(store):
    bad_draft = ManimSceneDraft(
        scene_id="intro-animation",
        source_scene_ids=("scene-intro",),
        visual_summary="Bad source.",
        generated_source="import os\nfrom manim import *\nclass SceneIntroAnimation(Scene): pass\n",
        estimated_duration_seconds=10.0,
    )
    llm = FakeManimLLMClient(draft=bad_draft)
    ctrl = _controller(store, llm_client=llm)

    with pytest.raises(ManimSourcePolicyError, match="os"):
        await _run(ctrl)


# ── 13: Idempotency key differs when brief changes ───────────────────────────


@pytest.mark.asyncio
async def test_idempotency_key_differs_for_different_briefs(store):
    ctrl = _controller(store)

    brief_a = _brief(animation_id="anim-a")
    brief_b = _brief(animation_id="anim-b")

    key_a = ctrl._compute_idempotency_key(brief_a, _CTX_HASH)
    key_b = ctrl._compute_idempotency_key(brief_b, _CTX_HASH)

    assert key_a != key_b


# ── 16: Different context_hash changes idempotency key ───────────────────────


@pytest.mark.asyncio
async def test_idempotency_key_differs_for_different_context(store):
    ctrl = _controller(store)
    brief = _brief()
    hash_a = hashlib.sha256(b"context-a").hexdigest()
    hash_b = hashlib.sha256(b"context-b").hexdigest()
    key_a = ctrl._compute_idempotency_key(brief, hash_a)
    key_b = ctrl._compute_idempotency_key(brief, hash_b)
    assert key_a != key_b


# ── 17: Output includes all expected artifact references ─────────────────────


@pytest.mark.asyncio
async def test_output_includes_all_artifact_refs(store):
    ctrl = _controller(store)
    output = await _run(ctrl)
    assert output.video is not None
    assert output.video_uri == output.video.uri
    assert output.generated_source is not None
    assert output.render_log is not None
    assert output.result_manifest is not None
    assert output.trace_uri is not None


# ── 18: Captions artifact present when runner returns captions ────────────────


@pytest.mark.asyncio
async def test_captions_artifact_present(store):
    ctrl = _controller(store, runner=FakeManimRenderRunner(include_captions=True))
    output = await _run(ctrl)
    assert output.captions is not None
    assert output.captions_uri is not None


# ── 19: Captions absent when runner returns no captions ──────────────────────


@pytest.mark.asyncio
async def test_captions_absent_when_runner_has_no_captions(store):
    ctrl = _controller(store, runner=FakeManimRenderRunner(include_captions=False))
    output = await _run(ctrl)
    assert output.captions is None
    assert output.captions_uri is None


# ── 19b: SRT captions from the renderer are normalised to WebVTT ─────────────

_SRT_CAPTIONS = (
    b"1\n00:00:00,000 --> 00:00:02,500\nWelcome to the scene.\n\n"
    b"2\n00:00:02,500 --> 00:00:05,000\nHere is the first card.\n"
)


@pytest.mark.asyncio
async def test_srt_captions_normalised_to_vtt(store):
    ctrl = _controller(store, runner=FakeManimRenderRunner(captions_bytes=_SRT_CAPTIONS))
    output = await _run(ctrl)
    assert output.captions_uri is not None
    assert output.captions_media_type == "text/vtt"
    published = await store.get_bytes(output.captions_uri)
    assert published.startswith(b"WEBVTT")
    assert b"00:00:02.500" in published  # SRT comma separator converted
    assert b"Welcome to the scene." in published


@pytest.mark.asyncio
async def test_garbage_captions_fail_media_validation(store):
    from learning_pipeline.tools.manim_video._contracts import ManimMediaValidationError

    ctrl = _controller(
        store, runner=FakeManimRenderRunner(captions_bytes=b"not captions at all")
    )
    with pytest.raises(ManimMediaValidationError, match="invalid captions"):
        await _run(ctrl)
