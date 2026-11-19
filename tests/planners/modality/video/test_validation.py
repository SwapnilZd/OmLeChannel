"""Video modality draft validation tests — Phase 13C."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    ModalityPlanningContext,
    NarrativeRole,
    ResolvedRLOContext,
    VideoModalityDraft,
    VideoSceneDraft,
)
from learning_pipeline.affordances.catalog import ModalityAffordanceCatalog, PlannerAffordanceView
from learning_pipeline.affordances.video import VIDEO_AFFORDANCES
from learning_pipeline.planners.modality.video.validation import (
    VideoModalityDraftValidationError,
    validate_video_modality_draft,
)

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-test",
  "title": "Test",
  "learner": {
    "role": "Manager", "deloitte_level": 55, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["test"], "business_context": {}
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-1", "rlo_version": "1.0", "order": 1,
      "selected_content": {
        "objective_ids": ["obj-1"],
        "concept_ids": ["con-1"],
        "component_ids": [],
        "assessment_item_ids": []
      },
      "starting_proficiency": "beginner",
      "target_proficiency": "intermediate",
      "content_depth": "working",
      "role_relevance": "test",
      "personalization_rationale": "test",
      "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [],
  "brand_contract": {},
  "sequencing_rationale": "test",
  "assessment_strategy": "test",
  "estimated_duration_minutes": 10,
  "source_rlo_versions": {"rlo-1": "1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)

_RLO_CTX = ResolvedRLOContext(
    rlo_id="rlo-1",
    rlo_version="1.0",
    order=1,
    title="Test RLO",
    topic="test",
    terminal_objective_text="Test terminal objective",
    enabling_objectives=(),
    concepts=(),
    components=(),
    assessment_items=(),
    selected_objective_ids=("obj-1",),
    selected_concept_ids=("con-1",),
    selected_component_ids=(),
    selected_assessment_ids=(),
    role_relevance="test",
    example_context=None,
    adaptation_instructions=(),
)

_CONTEXT = ModalityPlanningContext(
    blueprint_id="bp-test",
    learner=_BLUEPRINT.learner,
    rlo_contexts=(_RLO_CTX,),
)

_CATALOG = ModalityAffordanceCatalog(VIDEO_AFFORDANCES)
_AFFORDANCE_VIEW = PlannerAffordanceView(
    modality=Modality.VIDEO,
    affordances=_CATALOG.affordances_for(Modality.VIDEO),
)

_VALID_REF = RLOContentRef(
    rlo_id="rlo-1",
    rlo_version="1.0",
    objective_ids=("obj-1",),
    concept_ids=("con-1",),
)


def _scene(**kwargs) -> VideoSceneDraft:
    defaults = dict(
        scene_id="scene-a",
        source_content=(_VALID_REF,),
        learning_objective="Understand X",
        narrative_role=NarrativeRole.EXPLANATION,
        affordance_id="avatar_led_explanation",
        teaching_pattern="direct_instruction",
        content_direction="Explain X clearly.",
        presentation_direction="Avatar on solid background.",
        target_duration_seconds=60,
    )
    defaults.update(kwargs)
    return VideoSceneDraft(**defaults)


def _draft(*scenes: VideoSceneDraft, **kwargs) -> VideoModalityDraft:
    defaults = dict(
        draft_id="test-draft",
        title="Test Video",
        narrative="A test video narrative.",
        scenes=scenes or (_scene(),),
    )
    defaults.update(kwargs)
    return VideoModalityDraft(**defaults)


def _validate(draft: VideoModalityDraft, **kw):
    return validate_video_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW, **kw)


# ── Valid draft ───────────────────────────────────────────────────────────────


def test_valid_draft_passes():
    _validate(_draft())


# ── RLO reference integrity ───────────────────────────────────────────────────


def test_unknown_rlo_fails():
    bad_ref = RLOContentRef(rlo_id="rlo-unknown", rlo_version="1.0", objective_ids=("obj-1",))
    with pytest.raises(VideoModalityDraftValidationError, match="unknown RLO"):
        _validate(_draft(_scene(source_content=(bad_ref,))))


def test_wrong_rlo_version_fails():
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="9.9", objective_ids=("obj-1",))
    with pytest.raises(VideoModalityDraftValidationError, match="version"):
        _validate(_draft(_scene(source_content=(bad_ref,))))


# ── Content reference integrity ───────────────────────────────────────────────


def test_unselected_objective_fails():
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-NOTSEL",))
    with pytest.raises(VideoModalityDraftValidationError, match="objective"):
        _validate(_draft(_scene(source_content=(bad_ref,))))


def test_unselected_concept_fails():
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", concept_ids=("con-NOTSEL",))
    with pytest.raises(VideoModalityDraftValidationError, match="concept"):
        _validate(_draft(_scene(source_content=(bad_ref,))))


# ── Affordance validity ───────────────────────────────────────────────────────


def test_unknown_affordance_fails():
    with pytest.raises(VideoModalityDraftValidationError, match="affordance"):
        _validate(_draft(_scene(affordance_id="nonexistent_affordance")))


def test_capability_name_as_affordance_fails():
    with pytest.raises(VideoModalityDraftValidationError, match="capability"):
        _validate(_draft(_scene(affordance_id="video.avatar.render")))


def test_manim_capability_as_affordance_fails():
    with pytest.raises(VideoModalityDraftValidationError, match="capability"):
        _validate(_draft(_scene(affordance_id="manim.scene.create")))


# ── Asset reference validity ──────────────────────────────────────────────────


def test_unapproved_asset_reference_fails():
    with pytest.raises(VideoModalityDraftValidationError, match="asset"):
        _validate(
            _draft(_scene(
                affordance_id="avatar_with_existing_visual",
                referenced_asset_id="unknown-asset",
            )),
            approved_asset_ids=frozenset({"approved-asset-1"}),
        )


def test_approved_asset_reference_passes():
    view_with_asset = PlannerAffordanceView(
        modality=Modality.VIDEO,
        affordances=_CATALOG.affordances_for(Modality.VIDEO),
    )
    _validate(
        _draft(_scene(
            affordance_id="avatar_with_existing_visual",
            referenced_asset_id="approved-asset-1",
        )),
        approved_asset_ids=frozenset({"approved-asset-1"}),
    )


# ── Coverage ──────────────────────────────────────────────────────────────────


def test_uncovered_required_concept_fails():
    ref_no_concept = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-1",))
    with pytest.raises(VideoModalityDraftValidationError, match="concepts"):
        _validate(_draft(_scene(source_content=(ref_no_concept,))))


def test_coverage_report_returned_on_success():
    report = _validate(_draft())
    assert "obj-1" in report.covered_objective_ids
    assert "con-1" in report.covered_concept_ids


# ── Ordering ──────────────────────────────────────────────────────────────────


def test_ordering_single_rlo_passes():
    _validate(_draft(_scene()))


# ── Duration ─────────────────────────────────────────────────────────────────


def test_duration_within_limit_passes():
    _validate(_draft(_scene(target_duration_seconds=60)))


def test_total_duration_exceeds_limit_fails():
    import json
    bp_data = json.loads(_BLUEPRINT_JSON)
    bp_data["learner"]["duration_limit_minutes"] = 1  # 60 seconds limit
    bp = CourseBlueprint.model_validate(bp_data)
    with pytest.raises(VideoModalityDraftValidationError, match="duration"):
        validate_video_modality_draft(
            _draft(_scene(target_duration_seconds=120)),
            bp, _CONTEXT, _AFFORDANCE_VIEW,
        )
