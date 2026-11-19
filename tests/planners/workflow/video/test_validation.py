"""Tests for video draft validation — Phase 13B."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import ModalityPlan
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    VideoBackgroundDraft,
    
    VideoProductionDraft,
)
from learning_pipeline.planners.workflow.video.validation import (
    VideoDraftValidationError,
    validate_video_draft,
)

_VIDEO_PLAN_JSON = """{
  "plan_id": "mp-test-video",
  "modality": "video",
  "narrative": "test",
  "scenes": [
    {
      "id": "scene-a",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "obj-a",
      "teaching_pattern": "hook_then_rule",
      "preferred_capability": "avatar_video",
      "acceptable_fallbacks": [],
      "content_direction": "open with a hook"
    },
    {
      "id": "scene-b",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "obj-b",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "avatar_video",
      "acceptable_fallbacks": [],
      "content_direction": "explain the concepts"
    }
  ]
}"""


def _plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_VIDEO_PLAN_JSON)


def _solid_scene(
    scene_id: str = "scene-a",
    source_ids: tuple[str, ...] = ("scene-a",),
    script: str = "Hello world.",
    color: str = "#1A1A2E",
    duration: float = 60.0,
) -> AvatarVideoSceneDraft:
    return AvatarVideoSceneDraft(
        scene_id=scene_id,
        source_scene_ids=source_ids,
        script=script,
        background=VideoBackgroundDraft(kind="color", color=color),
        estimated_duration_seconds=duration,
    )


def _valid_draft() -> VideoProductionDraft:
    return VideoProductionDraft(
        draft_id="test-draft",
        title="Test Video",
        narrative_summary="A test video.",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            _solid_scene("scene-a", ("scene-a",)),
            _solid_scene("scene-b", ("scene-b",)),
        ),
        production_rationale="test",
    )


# ── render_capability ──────────────────────────────────────────────────────────


def test_valid_draft_passes():
    validate_video_draft(_valid_draft(), _plan())


def test_wrong_render_capability_fails():
    d = _valid_draft()
    bad = VideoProductionDraft(
        **{**d.model_dump(), "render_capability": "video.compose"},
    )
    with pytest.raises(VideoDraftValidationError, match="render_capability"):
        validate_video_draft(bad, _plan())


# ── scenes ────────────────────────────────────────────────────────────────────


def test_empty_scenes_fails():
    with pytest.raises(Exception):
        # Pydantic min_length=1 raises ValidationError
        VideoProductionDraft(
            draft_id="d",
            title="t",
            narrative_summary="n",
            render_capability="video.avatar.render",
            avatar_profile="default_instructor",
            voice_profile="default_instructor",
            width=1280,
            height=720,
            captions=False,
            scenes=(),
            production_rationale="r",
        )


def test_duplicate_scene_ids_fail_at_contract_level():
    with pytest.raises(Exception):
        # Pydantic model_validator catches duplicate scene_ids
        VideoProductionDraft(
            draft_id="d",
            title="t",
            narrative_summary="n",
            render_capability="video.avatar.render",
            avatar_profile="default_instructor",
            voice_profile="default_instructor",
            width=1280,
            height=720,
            captions=False,
            scenes=(
                _solid_scene("dup", ("scene-a",)),
                _solid_scene("dup", ("scene-b",)),
            ),
            production_rationale="r",
        )


def test_unknown_source_scene_id_fails():
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            _solid_scene("scene-a", ("scene-a",)),
            _solid_scene("scene-b", ("nonexistent-scene",)),
        ),
        production_rationale="r",
    )
    with pytest.raises(VideoDraftValidationError, match="nonexistent-scene"):
        validate_video_draft(d, _plan())


def test_uncovered_modality_scene_fails():
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            _solid_scene("scene-a", ("scene-a",)),
            # scene-b not covered
        ),
        production_rationale="r",
    )
    with pytest.raises(VideoDraftValidationError, match="scene-b"):
        validate_video_draft(d, _plan())


def test_blank_script_rejected_at_contract():
    with pytest.raises(Exception):
        AvatarVideoSceneDraft(
            scene_id="s1",
            source_scene_ids=("scene-a",),
            script="   ",
            background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
            estimated_duration_seconds=60.0,
        )


def test_nonpositive_duration_rejected_at_contract():
    with pytest.raises(Exception):
        AvatarVideoSceneDraft(
            scene_id="s1",
            source_scene_ids=("scene-a",),
            script="Hello.",
            background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
            estimated_duration_seconds=0.0,
        )


# ── scene order ───────────────────────────────────────────────────────────────


def test_out_of_order_scenes_fail():
    # scene-b before scene-a violates modality-plan order
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            _solid_scene("r-b", ("scene-b",)),
            _solid_scene("r-a", ("scene-a",)),
        ),
        production_rationale="r",
    )
    with pytest.raises(VideoDraftValidationError, match="order"):
        validate_video_draft(d, _plan())


def test_in_order_scenes_pass():
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            _solid_scene("r-a", ("scene-a",)),
            _solid_scene("r-b", ("scene-b",)),
        ),
        production_rationale="r",
    )
    validate_video_draft(d, _plan())


# ── profiles ──────────────────────────────────────────────────────────────────


def test_unknown_avatar_profile_fails():
    d = VideoProductionDraft(
        **{**_valid_draft().model_dump(), "avatar_profile": "unknown_avatar"},
    )
    with pytest.raises(VideoDraftValidationError, match="avatar_profile"):
        validate_video_draft(
            d,
            _plan(),
            approved_avatar_profiles=frozenset({"default_instructor"}),
        )


def test_unknown_voice_profile_fails():
    d = VideoProductionDraft(
        **{**_valid_draft().model_dump(), "voice_profile": "unknown_voice"},
    )
    with pytest.raises(VideoDraftValidationError, match="voice_profile"):
        validate_video_draft(
            d,
            _plan(),
            approved_voice_profiles=frozenset({"default_instructor"}),
        )


def test_approved_profiles_pass():
    validate_video_draft(
        _valid_draft(),
        _plan(),
        approved_avatar_profiles=frozenset({"default_instructor"}),
        approved_voice_profiles=frozenset({"default_instructor"}),
    )


# ── backgrounds ───────────────────────────────────────────────────────────────


def test_invalid_background_color_rejected_at_contract():
    with pytest.raises(Exception):
        VideoBackgroundDraft(kind="color", color="not-a-hex")


def test_valid_hex_color_passes():
    VideoBackgroundDraft(kind="color", color="#AABBCC")


def test_unknown_asset_id_fails():
    scene = AvatarVideoSceneDraft(
        scene_id="scene-a",
        source_scene_ids=("scene-a",),
        script="Hello.",
        background=VideoBackgroundDraft(kind="existing_asset", asset_id="unknown-asset"),
        estimated_duration_seconds=60.0,
    )
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            scene,
            _solid_scene("scene-b", ("scene-b",)),
        ),
        production_rationale="r",
    )
    with pytest.raises(VideoDraftValidationError, match="unknown-asset"):
        validate_video_draft(
            d,
            _plan(),
            approved_asset_ids=frozenset({"approved-asset"}),
        )


def test_known_asset_id_passes():
    scene = AvatarVideoSceneDraft(
        scene_id="scene-a",
        source_scene_ids=("scene-a",),
        script="Hello.",
        background=VideoBackgroundDraft(kind="existing_asset", asset_id="approved-asset"),
        estimated_duration_seconds=60.0,
    )
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            scene,
            _solid_scene("scene-b", ("scene-b",)),
        ),
        production_rationale="r",
    )
    validate_video_draft(
        d,
        _plan(),
        approved_asset_ids=frozenset({"approved-asset"}),
    )


# ── accessibility captions ────────────────────────────────────────────────────


def test_captions_required_but_false_fails():
    d = _valid_draft()
    assert not d.captions
    with pytest.raises(VideoDraftValidationError, match="[Cc]aptions"):
        validate_video_draft(d, _plan(), require_captions=True)


def test_captions_required_and_enabled_passes():
    d = VideoProductionDraft(**{**_valid_draft().model_dump(), "captions": True})
    validate_video_draft(d, _plan(), require_captions=True)


# ── provider ID heuristic ─────────────────────────────────────────────────────


def test_provider_id_in_scene_id_fails():
    scene = AvatarVideoSceneDraft(
        scene_id="Annie_expressive_public-scene",
        source_scene_ids=("scene-a",),
        script="Hello.",
        background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
        estimated_duration_seconds=60.0,
    )
    d = VideoProductionDraft(
        draft_id="d",
        title="t",
        narrative_summary="n",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=(
            scene,
            _solid_scene("scene-b", ("scene-b",)),
        ),
        production_rationale="r",
    )
    with pytest.raises(VideoDraftValidationError, match="provider"):
        validate_video_draft(d, _plan())
