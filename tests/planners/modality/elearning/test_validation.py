"""validate_elearning_modality_draft tests — Phase 14E.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  - Valid draft passes.
  - RLO version mismatch raises.
  - Unknown RLO ID raises.
  - Unselected objective raises.
  - Unselected concept raises.
  - Unselected assessment raises.
  - Unknown affordance raises.
  - Three-segment capability name as affordance raises.
  - Uncovered objective raises.
  - Blueprint ordering violation raises.
  - Duration exceeded raises (when limit set).
  - Duration not enforced when no limit.
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    ElearningModalityDraft,
    ElearningSceneDraft,
    ModalityPlanningContext,
    NarrativeRole,
    ResolvedRLOContext,
)
from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.affordances.elearning import build_elearning_affordance_catalog
from learning_pipeline.planners.modality.validation import ModalityDraftValidationError
from learning_pipeline.planners.modality.elearning.validation import (
    validate_elearning_modality_draft,
    compute_coverage_report,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-el-val-test",
  "title": "Validation Test",
  "learner": {
    "role": "Analyst", "deloitte_level": 45, "default_proficiency": "beginner",
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
        "assessment_item_ids": ["asm-1"]
      },
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "core",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    },
    {
      "rlo_id": "rlo-2", "rlo_version": "2.0", "order": 2,
      "selected_content": {
        "objective_ids": ["obj-2"],
        "concept_ids": [],
        "component_ids": [],
        "assessment_item_ids": []
      },
      "starting_proficiency": "intermediate", "target_proficiency": "advanced",
      "content_depth": "working", "role_relevance": "core",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "test", "assessment_strategy": "formative",
  "estimated_duration_minutes": 5, "source_rlo_versions": {"rlo-1": "1.0", "rlo-2": "2.0"}
}"""

_BLUEPRINT_WITH_LIMIT_JSON = """{
  "blueprint_id": "bp-el-val-limit",
  "title": "Validation Test Limit",
  "learner": {
    "role": "Analyst", "deloitte_level": 45, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["test"], "business_context": {},
    "duration_limit_minutes": 2
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-1", "rlo_version": "1.0", "order": 1,
      "selected_content": {
        "objective_ids": ["obj-1"],
        "concept_ids": [],
        "component_ids": [],
        "assessment_item_ids": []
      },
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "core",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "test", "assessment_strategy": "formative",
  "estimated_duration_minutes": 2, "source_rlo_versions": {"rlo-1": "1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)
_BLUEPRINT_WITH_LIMIT = CourseBlueprint.model_validate_json(_BLUEPRINT_WITH_LIMIT_JSON)

_RLO1_CTX = ResolvedRLOContext(
    rlo_id="rlo-1", rlo_version="1.0", order=1, title="RLO 1", topic="topic-1",
    terminal_objective_text="Understand topic 1",
    enabling_objectives=(), concepts=(), components=(), assessment_items=(),
    selected_objective_ids=("obj-1",), selected_concept_ids=("con-1",),
    selected_component_ids=(), selected_assessment_ids=("asm-1",),
    role_relevance="core", example_context=None, adaptation_instructions=(),
)

_RLO2_CTX = ResolvedRLOContext(
    rlo_id="rlo-2", rlo_version="2.0", order=2, title="RLO 2", topic="topic-2",
    terminal_objective_text="Understand topic 2",
    enabling_objectives=(), concepts=(), components=(), assessment_items=(),
    selected_objective_ids=("obj-2",), selected_concept_ids=(),
    selected_component_ids=(), selected_assessment_ids=(),
    role_relevance="core", example_context=None, adaptation_instructions=(),
)

_CONTEXT = ModalityPlanningContext(
    blueprint_id="bp-el-val-test",
    learner=_BLUEPRINT.learner,
    rlo_contexts=(_RLO1_CTX, _RLO2_CTX),
)

_LIMIT_CTX = ModalityPlanningContext(
    blueprint_id="bp-el-val-limit",
    learner=_BLUEPRINT_WITH_LIMIT.learner,
    rlo_contexts=(
        ResolvedRLOContext(
            rlo_id="rlo-1", rlo_version="1.0", order=1, title="RLO 1", topic="topic-1",
            terminal_objective_text="Understand",
            enabling_objectives=(), concepts=(), components=(), assessment_items=(),
            selected_objective_ids=("obj-1",), selected_concept_ids=(),
            selected_component_ids=(), selected_assessment_ids=(),
            role_relevance="core", example_context=None, adaptation_instructions=(),
        ),
    ),
)

_CATALOG = build_elearning_affordance_catalog()
_AFFORDANCE_VIEW = PlannerAffordanceView(
    modality=Modality.ELEARNING,
    affordances=_CATALOG.affordances_for(Modality.ELEARNING),
)

_REF1 = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-1",), concept_ids=("con-1",), assessment_item_ids=("asm-1",))
_REF2 = RLOContentRef(rlo_id="rlo-2", rlo_version="2.0", objective_ids=("obj-2",))
_LIMIT_REF = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-1",))


def _valid_scene(scene_id: str, ref: RLOContentRef, affordance: str = "elearning.static_explanation") -> ElearningSceneDraft:
    return ElearningSceneDraft(
        scene_id=scene_id,
        source_content=(ref,),
        learning_objective="Understand the topic.",
        narrative_role=NarrativeRole.EXPLANATION,
        affordance_id=affordance,
        teaching_pattern="direct_instruction",
        content_direction="Explain the concept clearly.",
        target_duration_seconds=60,
    )


def _valid_draft(scenes=None) -> ElearningModalityDraft:
    if scenes is None:
        scenes = (
            _valid_scene("scene-intro", _REF1),
            _valid_scene("scene-apply", _REF2),
        )
    return ElearningModalityDraft(
        draft_id="val-test-draft",
        title="Validation Test",
        narrative="A test narrative.",
        scenes=scenes,
    )


# ── Valid draft passes ─────────────────────────────────────────────────────────


def test_valid_draft_passes() -> None:
    draft = _valid_draft()
    coverage = validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)
    assert coverage is not None


def test_valid_draft_returns_coverage_report() -> None:
    draft = _valid_draft()
    coverage = validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)
    assert "obj-1" in coverage.covered_objective_ids
    assert "obj-2" in coverage.covered_objective_ids


# ── RLO reference errors ──────────────────────────────────────────────────────


def test_unknown_rlo_raises() -> None:
    bad_ref = RLOContentRef(rlo_id="rlo-UNKNOWN", rlo_version="1.0")
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="s1", source_content=(bad_ref,),
                learning_objective="obj", narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction", content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    with pytest.raises(ModalityDraftValidationError, match="rlo-UNKNOWN"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


def test_rlo_version_mismatch_raises() -> None:
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="9.9")
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="s1", source_content=(bad_ref,),
                learning_objective="obj", narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction", content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    with pytest.raises(ModalityDraftValidationError, match="version"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


# ── Content reference errors ──────────────────────────────────────────────────


def test_unselected_objective_raises() -> None:
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-NOT-SELECTED",))
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="s1", source_content=(bad_ref,),
                learning_objective="obj", narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction", content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    with pytest.raises(ModalityDraftValidationError, match="obj-NOT-SELECTED"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


def test_unselected_concept_raises() -> None:
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", concept_ids=("con-NOT-SELECTED",))
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="s1", source_content=(bad_ref,),
                learning_objective="obj", narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction", content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    with pytest.raises(ModalityDraftValidationError, match="con-NOT-SELECTED"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


def test_unselected_assessment_raises() -> None:
    bad_ref = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", assessment_item_ids=("asm-NOT-SELECTED",))
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="s1", source_content=(bad_ref,),
                learning_objective="obj", narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction", content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    with pytest.raises(ModalityDraftValidationError, match="asm-NOT-SELECTED"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


# ── Affordance errors ─────────────────────────────────────────────────────────


def test_unknown_affordance_raises() -> None:
    draft = _valid_draft(scenes=(
        _valid_scene("s1", _REF1, affordance="unknown.affordance"),
        _valid_scene("s2", _REF2),
    ))
    with pytest.raises(ModalityDraftValidationError, match="unknown.affordance"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


def test_capability_name_as_affordance_raises() -> None:
    draft = _valid_draft(scenes=(
        _valid_scene("s1", _REF1, affordance="elearning.course.author"),
        _valid_scene("s2", _REF2),
    ))
    with pytest.raises(ModalityDraftValidationError, match="capability"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


def test_manim_capability_as_affordance_raises() -> None:
    draft = _valid_draft(scenes=(
        _valid_scene("s1", _REF1, affordance="video.manim.render"),
        _valid_scene("s2", _REF2),
    ))
    with pytest.raises(ModalityDraftValidationError, match="capability"):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


# ── Coverage errors ───────────────────────────────────────────────────────────


def test_uncovered_objective_raises() -> None:
    # Only covers rlo-1/obj-1, not rlo-2/obj-2
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            _valid_scene("s1", _REF1),  # covers obj-1, con-1, asm-1 but not obj-2
        ),
    )
    with pytest.raises(ModalityDraftValidationError):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


# ── Ordering errors ───────────────────────────────────────────────────────────


def test_ordering_violation_raises() -> None:
    # Teaches rlo-2 before rlo-1 (violates blueprint order)
    draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            _valid_scene("s1", _REF2),  # rlo-2 first
            _valid_scene("s2", _REF1),  # rlo-1 second
        ),
    )
    with pytest.raises(
        ModalityDraftValidationError,
        match="rlo-2.*scene 0.*rlo-1.*scene 1",
    ):
        validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


def test_rlo_references_within_same_scene_have_no_order() -> None:
    scene = _valid_scene("s1", _REF1).model_copy(
        update={"source_content": (_REF2, _REF1)},
    )
    draft = _valid_draft(scenes=(scene,))

    validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)


# ── Duration errors ───────────────────────────────────────────────────────────


def test_duration_exceeded_raises() -> None:
    # limit = 2 min = 120s; total = 200s
    draft = ElearningModalityDraft(
        draft_id="limit-test", title="Over Limit", narrative="Over.",
        scenes=(
            ElearningSceneDraft(
                scene_id="s1", source_content=(_LIMIT_REF,),
                learning_objective="obj", narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction", content_direction="dir",
                target_duration_seconds=200,  # > 120
            ),
        ),
    )
    limit_view = PlannerAffordanceView(
        modality=Modality.ELEARNING,
        affordances=_CATALOG.affordances_for(Modality.ELEARNING),
    )
    with pytest.raises(ModalityDraftValidationError, match="duration"):
        validate_elearning_modality_draft(draft, _BLUEPRINT_WITH_LIMIT, _LIMIT_CTX, limit_view)


def test_duration_not_enforced_without_limit() -> None:
    # Blueprint has no duration_limit_minutes — very long draft is allowed
    draft = ElearningModalityDraft(
        draft_id="no-limit-test", title="No Limit", narrative="Unlimited.",
        scenes=(
            _valid_scene("s1", _REF1),
            _valid_scene("s2", _REF2),
        ),
    )
    coverage = validate_elearning_modality_draft(draft, _BLUEPRINT, _CONTEXT, _AFFORDANCE_VIEW)
    assert coverage is not None


# ── Coverage report ───────────────────────────────────────────────────────────


def test_coverage_report_shows_covered_ids() -> None:
    draft = _valid_draft()
    coverage = compute_coverage_report(draft, _CONTEXT)
    assert "obj-1" in coverage.covered_objective_ids
    assert "con-1" in coverage.covered_concept_ids


def test_coverage_report_shows_uncovered_ids() -> None:
    # Only cover rlo-1 content; rlo-2/obj-2 uncovered
    draft = ElearningModalityDraft(
        draft_id="partial", title="Partial", narrative="Partial.",
        scenes=(_valid_scene("s1", _REF1),),
    )
    coverage = compute_coverage_report(draft, _CONTEXT)
    assert "obj-2" in coverage.uncovered_objective_ids
