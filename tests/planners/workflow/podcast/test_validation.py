"""Tests for validate_podcast_draft — Phase 9."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.contracts import ModalityPlan
from learning_pipeline.contracts.planning import (
    OmittedScene,
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
)
from learning_pipeline.planners.workflow.podcast.validation import (
    PodcastDraftValidationError,
    validate_podcast_draft,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_PLAN_JSON = """{
  "plan_id": "mp-test",
  "modality": "podcast",
  "narrative": "test",
  "scenes": [
    {
      "id": "scene-a",
      "source_content": [
        {"rlo_id": "rlo-test", "rlo_version": "1.0.0", "objective_ids": ["lo-01"]}
      ],
      "learning_objective": "obj",
      "teaching_pattern": "hook_then_rule",
      "preferred_capability": "narration",
      "acceptable_fallbacks": [],
      "content_direction": "Introduce the concept."
    },
    {
      "id": "scene-b",
      "source_content": [
        {"rlo_id": "rlo-test", "rlo_version": "1.0.0", "objective_ids": ["lo-01"]}
      ],
      "learning_objective": "obj2",
      "teaching_pattern": "example_nonexample",
      "preferred_capability": "narration",
      "acceptable_fallbacks": [],
      "content_direction": "Provide examples."
    }
  ]
}"""


def _plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_PLAN_JSON)


def _seg(
    segment_id: str = "seg-01",
    source_scene_ids: tuple = ("scene-a",),
    speaker: str = "Host",
    text: str = "Hello world.",
    pause: float = 0.0,
) -> PodcastSpeechSegmentDraft:
    return PodcastSpeechSegmentDraft(
        segment_id=segment_id,
        source_scene_ids=source_scene_ids,
        speaker=speaker,
        text=text,
        learning_purpose="test",
        pause_after_seconds=pause,
    )


def _valid_draft() -> PodcastProductionDraft:
    return PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(
            _seg("seg-01", ("scene-a",)),
            _seg("seg-02", ("scene-b",), speaker="Expert"),
        ),
    )


# ── Valid draft passes ─────────────────────────────────────────────────────────


def test_valid_draft_passes() -> None:
    validate_podcast_draft(_valid_draft(), _plan())


def test_valid_draft_with_omitted_scene() -> None:
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(_seg("seg-01", ("scene-a",)),),
        omitted_scenes=(OmittedScene(scene_id="scene-b", rationale="Out of scope"),),
    )
    validate_podcast_draft(draft, _plan())


# ── Coverage check ────────────────────────────────────────────────────────────


def test_uncovered_scene_no_omission_fails() -> None:
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(_seg("seg-01", ("scene-a",)),),
    )
    with pytest.raises(PodcastDraftValidationError, match="scene-b"):
        validate_podcast_draft(draft, _plan())


# ── Unknown scene reference ────────────────────────────────────────────────────


def test_segment_referencing_unknown_scene_fails() -> None:
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(
            _seg("seg-01", ("scene-a",)),
            _seg("seg-02", ("scene-b", "scene-UNKNOWN"), speaker="Expert"),
        ),
    )
    with pytest.raises(PodcastDraftValidationError, match="scene-UNKNOWN"):
        validate_podcast_draft(draft, _plan())


# ── Speaker validation ─────────────────────────────────────────────────────────


def test_restricted_allowed_speakers_rejects_expert() -> None:
    """When allowed_speakers contains only Host, Expert segments are rejected."""
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(
            _seg("seg-01", ("scene-a",), speaker="Host"),
            _seg("seg-02", ("scene-b",), speaker="Expert"),
        ),
    )
    with pytest.raises(PodcastDraftValidationError, match="Expert"):
        validate_podcast_draft(draft, _plan(), allowed_speakers=frozenset({"Host"}))


# ── Text validation ────────────────────────────────────────────────────────────


def test_empty_text_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastSpeechSegmentDraft(
            segment_id="seg-01",
            source_scene_ids=("scene-a",),
            speaker="Host",
            text="",
            learning_purpose="test",
        )


# ── Negative pause ─────────────────────────────────────────────────────────────


def test_negative_pause_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastSpeechSegmentDraft(
            segment_id="seg-01",
            source_scene_ids=("scene-a",),
            speaker="Host",
            text="Hello.",
            learning_purpose="test",
            pause_after_seconds=-0.1,
        )


def test_response_length_pause_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastSpeechSegmentDraft(
            segment_id="seg-01",
            source_scene_ids=("scene-a",),
            speaker="Expert",
            text="Question for the Host.",
            learning_purpose="knowledge check",
            pause_after_seconds=1.1,
        )


def test_response_length_default_gap_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastProductionDraft(
            draft_id="d-01",
            title="Test",
            narrative_summary="A test episode.",
            segments=(_seg(),),
            default_gap_seconds=1.1,
        )


# ── Output filename ────────────────────────────────────────────────────────────


def test_safe_output_filename_passes() -> None:
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(
            _seg("seg-01", ("scene-a",)),
            _seg("seg-02", ("scene-b",), speaker="Expert"),
        ),
        output_filename="adkar-01.wav",
    )
    validate_podcast_draft(draft, _plan())


def test_path_separator_in_filename_fails() -> None:
    with pytest.raises(ValidationError):
        PodcastProductionDraft(
            draft_id="d-01",
            title="Test",
            narrative_summary="A test episode.",
            segments=(_seg("seg-01", ("scene-a",)),),
            output_filename="../etc/passwd",
        )


# ── Default gap ────────────────────────────────────────────────────────────────


def test_zero_default_gap_passes() -> None:
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(
            _seg("seg-01", ("scene-a",)),
            _seg("seg-02", ("scene-b",), speaker="Expert"),
        ),
        default_gap_seconds=0.0,
    )
    validate_podcast_draft(draft, _plan())


# ── Custom allowed speakers ───────────────────────────────────────────────────


def test_custom_allowed_speakers(monkeypatch) -> None:
    draft = PodcastProductionDraft(
        draft_id="d-01",
        title="Test",
        narrative_summary="A test episode.",
        segments=(
            _seg("seg-01", ("scene-a",), speaker="Host"),
            _seg("seg-02", ("scene-b",), speaker="Expert"),
        ),
    )
    # Expert not in custom set → should fail
    with pytest.raises(PodcastDraftValidationError, match="Expert"):
        validate_podcast_draft(draft, _plan(), allowed_speakers=frozenset({"Host"}))
