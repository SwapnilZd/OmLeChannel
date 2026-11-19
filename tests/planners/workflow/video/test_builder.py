"""Tests for VideoProductionPlanBuilder — Phase 13B."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import LiteralInput, Modality, ModalityProductionPlan
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    VideoBackgroundDraft,
    
    VideoProductionDraft,
)
from learning_pipeline.planners.workflow.video.builder import (
    RENDER_CAPABILITY,
    RENDER_JOB_ID,
    VideoProductionPlanBuilder,
    VideoProductionPlanBuilderError,
)


def _color_scene(
    scene_id: str = "s1",
    source_ids: tuple[str, ...] = ("modality-scene-1",),
    script: str = "Hello world.",
    duration: float = 60.0,
) -> AvatarVideoSceneDraft:
    return AvatarVideoSceneDraft(
        scene_id=scene_id,
        source_scene_ids=source_ids,
        script=script,
        background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
        estimated_duration_seconds=duration,
    )


def _valid_draft(scenes: tuple[AvatarVideoSceneDraft, ...] | None = None) -> VideoProductionDraft:
    return VideoProductionDraft(
        draft_id="video-test-draft",
        title="Test Video",
        narrative_summary="A test video.",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=scenes or (_color_scene("s1", ("ms-1",)), _color_scene("s2", ("ms-2",))),
        production_rationale="test",
    )


# ── One render job ─────────────────────────────────────────────────────────────


def test_build_produces_modality_production_plan():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert isinstance(plan, ModalityProductionPlan)


def test_build_produces_exactly_one_job():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert len(plan.jobs) == 1


def test_job_capability_is_avatar_render():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert plan.jobs[0].capability == RENDER_CAPABILITY


def test_job_id_is_render_avatar_video():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert plan.jobs[0].id == RENDER_JOB_ID


def test_job_is_deliverable():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert RENDER_JOB_ID in plan.deliverable_job_ids


def test_plan_modality_is_video():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert plan.modality == Modality.VIDEO


# ── Source lineage ────────────────────────────────────────────────────────────


def test_source_scene_ids_collected():
    draft = _valid_draft(scenes=(
        _color_scene("s1", ("ms-1",)),
        _color_scene("s2", ("ms-2",)),
    ))
    plan = VideoProductionPlanBuilder().build(draft)
    assert set(plan.jobs[0].source_scene_ids) == {"ms-1", "ms-2"}


def test_source_scene_ids_unique():
    draft = _valid_draft(scenes=(
        _color_scene("s1", ("ms-1", "ms-2")),
        _color_scene("s2", ("ms-2", "ms-3")),  # ms-2 appears twice
    ))
    plan = VideoProductionPlanBuilder().build(draft)
    ids = plan.jobs[0].source_scene_ids
    assert len(ids) == len(set(ids))


def test_source_scene_ids_preserve_order():
    draft = _valid_draft(scenes=(
        _color_scene("s1", ("ms-1",)),
        _color_scene("s2", ("ms-2",)),
    ))
    plan = VideoProductionPlanBuilder().build(draft)
    assert list(plan.jobs[0].source_scene_ids) == ["ms-1", "ms-2"]


# ── Input bindings ────────────────────────────────────────────────────────────


def test_deliverable_id_binding():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    inp = plan.jobs[0].inputs["deliverable_id"]
    assert isinstance(inp, LiteralInput)
    assert inp.value == "video-test-draft"


def test_avatar_binding():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    inp = plan.jobs[0].inputs["avatar"]
    assert isinstance(inp, LiteralInput)
    assert inp.value == {"profile": "default_instructor"}


def test_voice_binding():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    inp = plan.jobs[0].inputs["voice"]
    assert isinstance(inp, LiteralInput)
    assert inp.value == {"profile": "default_instructor", "speed": 1.0}


def test_dimensions_binding():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    inp = plan.jobs[0].inputs["dimensions"]
    assert isinstance(inp, LiteralInput)
    assert inp.value == {"width": 1280, "height": 720}


def test_captions_binding_false():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    inp = plan.jobs[0].inputs["captions"]
    assert isinstance(inp, LiteralInput)
    assert inp.value is False


def test_captions_binding_true():
    draft = VideoProductionDraft(**{**_valid_draft().model_dump(), "captions": True})
    plan = VideoProductionPlanBuilder().build(draft)
    assert plan.jobs[0].inputs["captions"].value is True


def test_scenes_binding_contains_scripts():
    draft = _valid_draft(scenes=(
        _color_scene("s1", ("ms-1",), script="First script."),
        _color_scene("s2", ("ms-2",), script="Second script."),
    ))
    plan = VideoProductionPlanBuilder().build(draft)
    scenes_value = plan.jobs[0].inputs["scenes"].value
    assert scenes_value[0]["script"] == "First script."
    assert scenes_value[1]["script"] == "Second script."


def test_scenes_binding_preserves_order():
    draft = _valid_draft(scenes=(
        _color_scene("s1", ("ms-1",)),
        _color_scene("s2", ("ms-2",)),
    ))
    plan = VideoProductionPlanBuilder().build(draft)
    scenes_value = plan.jobs[0].inputs["scenes"].value
    assert [s["scene_id"] for s in scenes_value] == ["s1", "s2"]


def test_scenes_binding_color_background():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    bg = plan.jobs[0].inputs["scenes"].value[0]["background"]
    assert bg == {"kind": "color", "color": "#1A1A2E"}


# ── Asset resolution ──────────────────────────────────────────────────────────


def test_existing_asset_background_resolves_to_image():
    scene = AvatarVideoSceneDraft(
        scene_id="s1",
        source_scene_ids=("ms-1",),
        script="Hello.",
        background=VideoBackgroundDraft(kind="existing_asset", asset_id="brand-bg"),
        estimated_duration_seconds=30.0,
    )
    draft = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(scene,),
        production_rationale="r",
    )
    builder = VideoProductionPlanBuilder(asset_catalog={"brand-bg": "artifact://backgrounds/brand-bg.png"})
    plan = builder.build(draft)
    bg = plan.jobs[0].inputs["scenes"].value[0]["background"]
    assert bg == {"kind": "image", "artifact_uri": "artifact://backgrounds/brand-bg.png"}


def test_missing_asset_raises():
    scene = AvatarVideoSceneDraft(
        scene_id="s1",
        source_scene_ids=("ms-1",),
        script="Hello.",
        background=VideoBackgroundDraft(kind="existing_asset", asset_id="missing-bg"),
        estimated_duration_seconds=30.0,
    )
    draft = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(scene,),
        production_rationale="r",
    )
    with pytest.raises(VideoProductionPlanBuilderError, match="missing-bg"):
        VideoProductionPlanBuilder().build(draft)


# ── Output keys ───────────────────────────────────────────────────────────────


def test_output_keys_are_correct():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert set(plan.jobs[0].output_keys) == {
        "video_uri",
        "subtitle_uri",
        "cost_report_uri",
        "duration_seconds",
        "usage",
    }


# ── Determinism ───────────────────────────────────────────────────────────────


def test_repeated_builds_are_identical():
    draft = _valid_draft()
    builder = VideoProductionPlanBuilder()
    p1 = builder.build(draft)
    p2 = builder.build(draft)
    assert p1.model_dump() == p2.model_dump()


def test_plan_id_is_derived_from_draft_id():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert plan.plan_id == "pp-video-test-draft"


def test_no_dependencies_on_render_job():
    plan = VideoProductionPlanBuilder().build(_valid_draft())
    assert plan.jobs[0].depends_on == ()
