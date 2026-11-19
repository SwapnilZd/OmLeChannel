"""Tests for modality draft validation (coverage, ordering, duration) — Phase 10."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.affordances.podcast import (
    PODCAST_SUPPORT_RULES,
    build_podcast_affordance_catalog,
    compute_producible_affordances,
)
from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    ModalityPlanningContext,
    NarrativeRole,
    PodcastModalityDraft,
    PodcastSceneDraft,
    ResolvedContentItem,
    ResolvedRLOContext,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.common import Modality
from learning_pipeline.planners.modality.validation import (
    ModalityDraftValidationError,
    check_coverage,
)
from learning_pipeline.planners.modality.podcast.validation import (
    check_duration,
    check_ordering,
    compute_coverage_report,
    validate_podcast_modality_draft,
)

_RLO_ROOT = Path(__file__).parents[3] / "examples" / "reference" / "rlos"
_BP_PATH = Path(__file__).parents[3] / "examples" / "reference" / "podcast" / "course_blueprint.json"

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


# ── Shared helpers ────────────────────────────────────────────────────────────


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_affordance_view() -> PlannerAffordanceView:
    catalog = build_podcast_affordance_catalog()
    return compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, _PODCAST_CAPS, Modality.PODCAST)


def _make_learner(duration_limit: int | None = 10) -> LearnerContext:
    return LearnerContext(
        role="Manager",
        deloitte_level=55,
        default_proficiency="beginner",
        topic_proficiencies={},
        goals=["test"],
        duration_limit_minutes=duration_limit,
        business_context={},
    )


def _make_rlo_context(rlo_id: str = "rlo-a", version: str = "1.0.0", order: int = 1) -> ResolvedRLOContext:
    return ResolvedRLOContext(
        rlo_id=rlo_id,
        rlo_version=version,
        order=order,
        title="Test RLO",
        topic="Testing",
        terminal_objective_text="Test terminal objective",
        enabling_objectives=(ResolvedContentItem(
            rlo_id=rlo_id, rlo_version=version, content_type="objective",
            content_id="lo-01", title=None, content="Objective content",
        ),),
        concepts=(ResolvedContentItem(
            rlo_id=rlo_id, rlo_version=version, content_type="concept",
            content_id="c-01", title="Concept A", content="Concept content",
        ),),
        components=(
            ResolvedContentItem(rlo_id=rlo_id, rlo_version=version, content_type="component",
                                content_id="comp-01", title="Hook", content="Hook content"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version=version, content_type="component",
                                content_id="comp-02", title="Rule", content="Rule content"),
        ),
        assessment_items=(ResolvedContentItem(
            rlo_id=rlo_id, rlo_version=version, content_type="assessment_item",
            content_id="q-01", title="Q1", content="Question content",
        ),),
        selected_objective_ids=("lo-01",),
        selected_concept_ids=("c-01",),
        selected_component_ids=("comp-01", "comp-02"),
        selected_assessment_ids=("q-01",),
        role_relevance="Relevant to manager",
        example_context=None,
        adaptation_instructions=(),
    )


def _make_context(rlo_contexts: tuple = ()) -> ModalityPlanningContext:
    return ModalityPlanningContext(
        blueprint_id="bp-test",
        learner=_make_learner(),
        rlo_contexts=rlo_contexts or (_make_rlo_context(),),
        estimated_duration_minutes=10,
    )


def _full_ref(rlo_id: str = "rlo-a", version: str = "1.0.0") -> RLOContentRef:
    return RLOContentRef(
        rlo_id=rlo_id,
        rlo_version=version,
        objective_ids=("lo-01",),
        concept_ids=("c-01",),
        component_ids=("comp-01", "comp-02"),
        assessment_item_ids=("q-01",),
    )


def _make_valid_draft(rlo_id: str = "rlo-a", version: str = "1.0.0") -> PodcastModalityDraft:
    return PodcastModalityDraft(
        draft_id="test-draft",
        title="Test Episode",
        narrative="A test episode narrative.",
        scenes=(
            PodcastSceneDraft(
                scene_id="scene-01",
                source_content=(_full_ref(rlo_id, version),),
                learning_objective="Understand the concept",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct_instruction",
                content_direction="Teach the concept.",
                target_duration_seconds=300,
            ),
        ),
    )


# ── Pydantic-level validation ─────────────────────────────────────────────────


def test_empty_scenes_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastModalityDraft(draft_id="d", title="T", narrative="N", scenes=())


def test_duplicate_scene_ids_rejected_by_pydantic() -> None:
    scene = PodcastSceneDraft(
        scene_id="scene-01",
        source_content=(_full_ref(),),
        learning_objective="obj",
        narrative_role=NarrativeRole.EXPLANATION,
        affordance_id="host_expert_dialogue",
        teaching_pattern="direct",
        content_direction="direction",
        target_duration_seconds=60,
    )
    with pytest.raises(ValidationError):
        PodcastModalityDraft(draft_id="d", title="T", narrative="N", scenes=(scene, scene))


def test_non_positive_duration_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastSceneDraft(
            scene_id="scene-01",
            source_content=(_full_ref(),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="direction",
            target_duration_seconds=0,
        )


def test_empty_source_content_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        PodcastSceneDraft(
            scene_id="scene-01",
            source_content=(),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="direction",
            target_duration_seconds=60,
        )


# ── Valid draft passes ────────────────────────────────────────────────────────


def test_valid_draft_passes() -> None:
    blueprint = _load_blueprint()
    context = _make_context((_make_rlo_context(
        "rlo-adkar-01-name-and-sequence", "1.1.0"
    ),))
    # Use a draft that covers all selected content (matches _make_rlo_context defaults)
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(
            PodcastSceneDraft(
                scene_id="s1",
                source_content=(RLOContentRef(
                    rlo_id="rlo-adkar-01-name-and-sequence",
                    rlo_version="1.1.0",
                    objective_ids=("lo-01",),
                    concept_ids=("c-01",),
                    component_ids=("comp-01", "comp-02"),
                    assessment_item_ids=("q-01",),
                ),),
                learning_objective="Name ADKAR elements",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct_instruction",
                content_direction="Teach ADKAR.",
                target_duration_seconds=300,
            ),
        ),
    )
    coverage = validate_podcast_modality_draft(draft, blueprint, context, _make_affordance_view())
    assert not coverage.uncovered_objective_ids
    assert not coverage.uncovered_concept_ids


# ── RLO reference integrity ───────────────────────────────────────────────────


def test_unknown_rlo_id_fails() -> None:
    from learning_pipeline.contracts.assembly import (
        TailoredRLORef, RLOContentSelection, CourseBlueprint
    )
    draft = _make_valid_draft(rlo_id="rlo-UNKNOWN", version="1.0.0")
    blueprint = _load_blueprint()
    context = _make_context()
    with pytest.raises(ModalityDraftValidationError, match="UNKNOWN"):
        validate_podcast_modality_draft(draft, blueprint, context, _make_affordance_view())


def test_wrong_rlo_version_fails() -> None:
    draft = _make_valid_draft(rlo_id="rlo-adkar-01-name-and-sequence", version="9.9.9")
    blueprint = _load_blueprint()
    context = _make_context()
    with pytest.raises(ModalityDraftValidationError, match="9.9.9"):
        validate_podcast_modality_draft(draft, blueprint, context, _make_affordance_view())


# ── Content reference integrity ───────────────────────────────────────────────


def test_unselected_component_reference_fails() -> None:
    context = _make_context()  # selected_component_ids = ("comp-01", "comp-02")
    blueprint = _load_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(RLOContentRef(
                rlo_id="rlo-adkar-01-name-and-sequence",
                rlo_version="1.1.0",
                component_ids=("comp-UNSELECTED",),
            ),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="direction",
            target_duration_seconds=60,
        ),),
    )
    with pytest.raises(ModalityDraftValidationError, match="comp-UNSELECTED"):
        validate_podcast_modality_draft(draft, blueprint, context, _make_affordance_view())


# ── Affordance validity ───────────────────────────────────────────────────────


def test_unknown_affordance_fails() -> None:
    rlo_id = "rlo-adkar-01-name-and-sequence"
    context = _make_context((_make_rlo_context(rlo_id, "1.1.0"),))
    blueprint = _load_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(_full_ref(rlo_id, "1.1.0"),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="NOT_A_REAL_AFFORDANCE",
            teaching_pattern="direct",
            content_direction="direction",
            target_duration_seconds=60,
        ),),
    )
    with pytest.raises(ModalityDraftValidationError, match="NOT_A_REAL_AFFORDANCE"):
        validate_podcast_modality_draft(draft, blueprint, context, _make_affordance_view())


# ── Coverage ──────────────────────────────────────────────────────────────────


def test_complete_coverage_passes() -> None:
    context = _make_context()
    draft = _make_valid_draft()
    coverage = compute_coverage_report(draft, context)
    assert not coverage.uncovered_objective_ids
    assert not coverage.uncovered_concept_ids
    assert not coverage.uncovered_component_ids
    assert not coverage.uncovered_assessment_ids


def test_missing_objective_is_uncovered() -> None:
    context = _make_context()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(RLOContentRef(
                rlo_id="rlo-a",
                rlo_version="1.0.0",
                # No objective_ids → lo-01 not covered
                concept_ids=("c-01",),
                component_ids=("comp-01", "comp-02"),
                assessment_item_ids=("q-01",),
            ),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="direction",
            target_duration_seconds=60,
        ),),
    )
    coverage = compute_coverage_report(draft, context)
    assert "lo-01" in coverage.uncovered_objective_ids


def test_missing_concept_fails_check_coverage() -> None:
    context = _make_context()
    from learning_pipeline.contracts.planning import ModalityCoverageReport
    coverage = ModalityCoverageReport(uncovered_concept_ids=("c-01",))
    with pytest.raises(ModalityDraftValidationError, match="c-01"):
        check_coverage(coverage)


def test_duplicate_coverage_produces_warning() -> None:
    context = _make_context()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(
            PodcastSceneDraft(
                scene_id="s1",
                source_content=(RLOContentRef(
                    rlo_id="rlo-a", rlo_version="1.0.0",
                    objective_ids=("lo-01",), concept_ids=("c-01",),
                    component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",),
                ),),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=60,
            ),
            PodcastSceneDraft(
                scene_id="s2",
                source_content=(RLOContentRef(
                    rlo_id="rlo-a", rlo_version="1.0.0",
                    objective_ids=("lo-01",),  # lo-01 covered again
                ),),
                learning_objective="recap",
                narrative_role=NarrativeRole.SUMMARY,
                affordance_id="summary_recap",
                teaching_pattern="summary",
                content_direction="d",
                target_duration_seconds=30,
            ),
        ),
    )
    coverage = compute_coverage_report(draft, context)
    assert any("lo-01" in w for w in coverage.duplicate_coverage_warnings)


# ── Ordering ──────────────────────────────────────────────────────────────────


def _two_rlo_context() -> ModalityPlanningContext:
    return ModalityPlanningContext(
        blueprint_id="bp-test",
        learner=_make_learner(),
        rlo_contexts=(
            _make_rlo_context("rlo-a", "1.0.0", order=1),
            _make_rlo_context("rlo-b", "1.0.0", order=2),
        ),
        estimated_duration_minutes=20,
    )


def _two_rlo_blueprint() -> CourseBlueprint:
    from learning_pipeline.contracts.assembly import (
        TailoredRLORef, RLOContentSelection, CourseBlueprint
    )
    from learning_pipeline.contracts.learner import LearnerContext
    learner = _make_learner(20)
    ref_a = TailoredRLORef(
        rlo_id="rlo-a", rlo_version="1.0.0", order=1,
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",), concept_ids=("c-01",),
            component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",),
        ),
        starting_proficiency="beginner", target_proficiency="beginner",
        role_relevance="relevant", personalization_rationale="reason",
        sequencing_rationale="reason",
    )
    ref_b = TailoredRLORef(
        rlo_id="rlo-b", rlo_version="1.0.0", order=2,
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",), concept_ids=("c-01",),
            component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",),
        ),
        starting_proficiency="beginner", target_proficiency="beginner",
        role_relevance="relevant", personalization_rationale="reason",
        sequencing_rationale="reason",
    )
    return CourseBlueprint(
        blueprint_id="bp-two-rlo",
        learner=learner,
        title="Two RLO Course",
        learning_outcomes=("outcome-1",),
        ordered_rlo_refs=(ref_a, ref_b),
        sequencing_rationale="reason",
        assessment_strategy="quiz",
        estimated_duration_minutes=20,
        source_rlo_versions={"rlo-a": "1.0.0", "rlo-b": "1.0.0"},
    )


def test_correct_ordering_passes() -> None:
    blueprint = _two_rlo_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(
            PodcastSceneDraft(
                scene_id="s1",
                source_content=(RLOContentRef(rlo_id="rlo-a", rlo_version="1.0.0",
                                              objective_ids=("lo-01",), concept_ids=("c-01",),
                                              component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",)),),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=120,
            ),
            PodcastSceneDraft(
                scene_id="s2",
                source_content=(RLOContentRef(rlo_id="rlo-b", rlo_version="1.0.0",
                                              objective_ids=("lo-01",), concept_ids=("c-01",),
                                              component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",)),),
                learning_objective="obj2",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=120,
            ),
        ),
    )
    check_ordering(draft, blueprint)  # Should not raise


def test_reversed_initial_order_fails() -> None:
    blueprint = _two_rlo_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(
            # rlo-b BEFORE rlo-a — violates blueprint ordering
            PodcastSceneDraft(
                scene_id="s1",
                source_content=(RLOContentRef(rlo_id="rlo-b", rlo_version="1.0.0",
                                              objective_ids=("lo-01",), concept_ids=("c-01",),
                                              component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",)),),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=120,
            ),
            PodcastSceneDraft(
                scene_id="s2",
                source_content=(RLOContentRef(rlo_id="rlo-a", rlo_version="1.0.0",
                                              objective_ids=("lo-01",), concept_ids=("c-01",),
                                              component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",)),),
                learning_objective="obj2",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=120,
            ),
        ),
    )
    with pytest.raises(ModalityDraftValidationError):
        check_ordering(draft, blueprint)


def test_later_recap_reference_does_not_violate_ordering() -> None:
    blueprint = _two_rlo_blueprint()
    # Scene order: A, B, A (recap) — A's recap at end is fine
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(
            PodcastSceneDraft(
                scene_id="s1",
                source_content=(RLOContentRef(rlo_id="rlo-a", rlo_version="1.0.0",
                                              objective_ids=("lo-01",), concept_ids=("c-01",),
                                              component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",)),),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=100,
            ),
            PodcastSceneDraft(
                scene_id="s2",
                source_content=(RLOContentRef(rlo_id="rlo-b", rlo_version="1.0.0",
                                              objective_ids=("lo-01",), concept_ids=("c-01",),
                                              component_ids=("comp-01", "comp-02"), assessment_item_ids=("q-01",)),),
                learning_objective="obj2",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="direct",
                content_direction="d",
                target_duration_seconds=100,
            ),
            PodcastSceneDraft(
                scene_id="s3",
                source_content=(RLOContentRef(rlo_id="rlo-a", rlo_version="1.0.0"),),
                learning_objective="recap rlo-a",
                narrative_role=NarrativeRole.SUMMARY,
                affordance_id="summary_recap",
                teaching_pattern="recap",
                content_direction="recap rlo-a",
                target_duration_seconds=30,
            ),
        ),
    )
    check_ordering(draft, blueprint)  # Should not raise


# ── Duration ──────────────────────────────────────────────────────────────────


def test_duration_within_limit_passes() -> None:
    blueprint = _load_blueprint()
    draft = _make_valid_draft(
        rlo_id="rlo-adkar-01-name-and-sequence", version="1.1.0"
    )
    # target_duration_seconds=300 < 600 limit
    check_duration(draft, blueprint)


def test_duration_exceeding_limit_fails() -> None:
    blueprint = _load_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(_full_ref("rlo-adkar-01-name-and-sequence", "1.1.0"),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="d",
            target_duration_seconds=700,  # exceeds 600s limit
        ),),
    )
    with pytest.raises(ModalityDraftValidationError, match="700"):
        check_duration(draft, blueprint)


def test_duration_exactly_at_limit_passes() -> None:
    blueprint = _load_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(_full_ref("rlo-adkar-01-name-and-sequence", "1.1.0"),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="d",
            target_duration_seconds=600,
        ),),
    )
    check_duration(draft, blueprint)  # Should not raise
