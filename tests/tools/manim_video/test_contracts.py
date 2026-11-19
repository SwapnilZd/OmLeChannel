"""Tests for manim_video._contracts (ManimSceneDraft, ManimRenderPolicy, errors)."""
from __future__ import annotations

import pytest

from learning_pipeline.tools.manim_video._contracts import (
    ManimError,
    ManimInfrastructureError,
    ManimMediaValidationError,
    ManimPolicyError,
    ManimRenderError,
    ManimRenderPolicy,
    ManimRenderRequest,
    ManimRenderResult,
    ManimRepairBudgetError,
    ManimSceneDraft,
    ManimSourcePolicyError,
    ManimTrace,
)


# ── ManimSceneDraft ───────────────────────────────────────────────────────────


def test_scene_draft_template_path_valid():
    draft = ManimSceneDraft(
        scene_id="intro",
        source_scene_ids=("s1",),
        template_id="vertical_stack",
        visual_summary="Three stacked cards.",
        component_bindings={"title": "Intro"},
        estimated_duration_seconds=60.0,
    )
    assert draft.template_id == "vertical_stack"
    assert draft.generated_source is None


def test_scene_draft_generated_source_path_valid():
    draft = ManimSceneDraft(
        scene_id="intro",
        source_scene_ids=("s1",),
        visual_summary="Simple title card.",
        generated_source=(
            "from manim import *\n"
            "from manim_voiceover import VoiceoverScene\n"
            "class Scene_intro(VoiceoverScene):\n"
            "    def construct(self):\n"
            "        with self.voiceover(text='Narration.') as tracker:\n"
            "            self.wait(tracker.duration)\n"
        ),
        estimated_duration_seconds=30.0,
    )
    assert draft.template_id is None
    assert draft.generated_source is not None


def test_scene_draft_requires_template_or_source():
    with pytest.raises(Exception, match="template_id or generated_source"):
        ManimSceneDraft(
            scene_id="x",
            source_scene_ids=("s1",),
            visual_summary="Missing both.",
            estimated_duration_seconds=10.0,
        )


def test_scene_draft_rejects_empty_source_scene_ids():
    with pytest.raises(Exception, match="source_scene_ids must not be empty"):
        ManimSceneDraft(
            scene_id="x",
            source_scene_ids=(),
            visual_summary="No scenes.",
            generated_source="from manim import *\n",
            estimated_duration_seconds=10.0,
        )


def test_scene_draft_rejects_nonpositive_duration():
    with pytest.raises(Exception):
        ManimSceneDraft(
            scene_id="x",
            source_scene_ids=("s1",),
            visual_summary="Zero duration.",
            generated_source="from manim import *\n",
            estimated_duration_seconds=0.0,
        )


def test_scene_draft_rejects_blank_scene_id():
    with pytest.raises(Exception):
        ManimSceneDraft(
            scene_id="",
            source_scene_ids=("s1",),
            visual_summary="Blank ID.",
            generated_source="from manim import *\n",
            estimated_duration_seconds=10.0,
        )


# ── ManimRenderPolicy ─────────────────────────────────────────────────────────


def test_render_policy_defaults():
    policy = ManimRenderPolicy()
    assert policy.max_render_attempts == 3
    assert policy.render_timeout_seconds == 300
    assert policy.duration_tolerance_seconds == 10.0


def test_render_policy_custom():
    policy = ManimRenderPolicy(max_render_attempts=1, render_timeout_seconds=60)
    assert policy.max_render_attempts == 1


# ── ManimRenderRequest ────────────────────────────────────────────────────────


def test_render_request_valid():
    req = ManimRenderRequest(
        job_id="job-1",
        idempotency_key="abcdef",
        scene_class="SceneIntro",
        source_code="from manim import *\n",
        quality="medium_quality",
    )
    assert req.expected_duration_seconds is None


# ── ManimRenderResult ─────────────────────────────────────────────────────────


def test_render_result_success():
    result = ManimRenderResult(
        status="success",
        video_bytes=b"\x00\x00\x00\x0cftyp",
        log_bytes=b"OK",
        duration_seconds=45.0,
    )
    assert result.status == "success"
    assert result.failure_message is None


def test_render_result_failure():
    result = ManimRenderResult(
        status="failure",
        log_bytes=b"Error",
        failure_category="source_error",
        failure_message="NameError: foo not defined",
    )
    assert result.video_bytes is None


# ── ManimTrace ────────────────────────────────────────────────────────────────


def test_trace_valid():
    trace = ManimTrace(
        workflow_id="wf-1",
        task_id="t-1",
        animation_id="intro",
        idempotency_key="abc123",
        prompt_version="manim_scene_draft_v1",
        model="gpt-5.6",
        model_call_count=1,
        repair_attempt_count=0,
        render_attempt_count=1,
        source_scene_ids=("s1",),
    )
    assert trace.source_repaired is False
    assert trace.checkpoint_stages_reused == ()


# ── Error hierarchy ───────────────────────────────────────────────────────────


def test_error_hierarchy():
    assert issubclass(ManimPolicyError, ManimError)
    assert issubclass(ManimRepairBudgetError, ManimError)
    assert issubclass(ManimSourcePolicyError, ManimError)
    assert issubclass(ManimInfrastructureError, ManimError)
    assert issubclass(ManimRenderError, ManimError)
    assert issubclass(ManimMediaValidationError, ManimError)


def test_manim_settings_render_timeout_default_and_override(monkeypatch):
    """Render timeout must be deployment-tunable: a 13-beat, 3-minute scene
    legitimately needs more container wall clock than short scenes, and a
    too-small cap fails deterministically on every retry."""
    from learning_pipeline.config import load_manim_settings

    monkeypatch.setenv("LITE_LLM_BASE_URL", "http://litellm.test:4000")
    monkeypatch.setenv("LITE_LLM_API_KEY", "sk-test")
    monkeypatch.delenv("MANIM_RENDER_TIMEOUT_SECONDS", raising=False)
    assert load_manim_settings().render_timeout_seconds == 900

    monkeypatch.setenv("MANIM_RENDER_TIMEOUT_SECONDS", "1200")
    assert load_manim_settings().render_timeout_seconds == 1200
