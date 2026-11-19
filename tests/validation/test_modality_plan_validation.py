"""Tests for validate_modality_plan — cross-contract modality plan validation."""

from __future__ import annotations

import json
import pathlib

import pytest

from learning_pipeline.contracts import (
    CourseBlueprint,
    LearnerContext,
    Modality,
    ModalityPlan,
    ModalityScene,
    RLOContentRef,
    RLOContentSelection,
    RLODocument,
    TailoredRLORef,
    TopicProficiency,
)
from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.modality_plan import validate_modality_plan

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_RLO_PATH = _REPO_ROOT / "course-definitions" / "rlos" / "rlo-adkar-01-name-and-sequence.json"
_FIXTURE_DIR = _REPO_ROOT / "examples" / "reference" / "podcast"

_ALLOWED = frozenset({"narration"})
_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Learn ADKAR",),
)


@pytest.fixture(scope="module")
def rlo() -> RLODocument:
    return RLODocument.model_validate(json.loads(_RLO_PATH.read_text()))


@pytest.fixture(scope="module")
def blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate(
        json.loads((_FIXTURE_DIR / "course_blueprint.json").read_text())
    )


@pytest.fixture(scope="module")
def modality_plan() -> ModalityPlan:
    return ModalityPlan.model_validate(
        json.loads((_FIXTURE_DIR / "modality_plan.json").read_text())
    )


def _make_blueprint(
    rlo_id: str = "rlo-adkar-01-name-and-sequence",
    rlo_version: str = "1.1.0",
    selected_content: RLOContentSelection | None = None,
) -> CourseBlueprint:
    if selected_content is None:
        selected_content = RLOContentSelection(
            objective_ids=("lo-01",),
            concept_ids=("c-01",),
            component_ids=("comp-hook-01", "comp-rule-01", "comp-example-01"),
            assessment_item_ids=("q-01",),
        )
    ref = TailoredRLORef(
        rlo_id=rlo_id,
        rlo_version=rlo_version,
        order=1,
        selected_content=selected_content,
        starting_proficiency=TopicProficiency.BEGINNER,
        target_proficiency=TopicProficiency.INTERMEDIATE,
        role_relevance="relevant",
        personalization_rationale="rationale",
        sequencing_rationale="sequence",
    )
    return CourseBlueprint(
        blueprint_id="bp-test",
        learner=_LEARNER,
        title="Test Blueprint",
        learning_outcomes=("outcome 1",),
        ordered_rlo_refs=(ref,),
        sequencing_rationale="sequence",
        assessment_strategy="assessment",
        estimated_duration_minutes=10,
        source_rlo_versions={rlo_id: rlo_version},
    )


def _make_scene(
    scene_id: str = "scene-1",
    preferred_capability: str = "narration",
    component_ids: tuple[str, ...] = ("comp-hook-01",),
    assessment_ids: tuple[str, ...] = (),
    rlo_id: str = "rlo-adkar-01-name-and-sequence",
    rlo_version: str = "1.1.0",
) -> ModalityScene:
    return ModalityScene(
        id=scene_id,
        source_content=(
            RLOContentRef(
                rlo_id=rlo_id,
                rlo_version=rlo_version,
                objective_ids=("lo-01",),
                concept_ids=("c-01",),
                component_ids=component_ids,
                assessment_item_ids=assessment_ids,
            ),
        ),
        learning_objective="objective",
        teaching_pattern="explanation",
        preferred_capability=preferred_capability,
        content_direction="direction",
    )


def _make_plan(scenes: tuple[ModalityScene, ...]) -> ModalityPlan:
    return ModalityPlan(
        plan_id="mp-test",
        modality=Modality.PODCAST,
        narrative="test",
        scenes=scenes,
    )


# ── Happy path ────────────────────────────────────────────────────────────────


def test_reference_modality_plan_passes(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_plan: ModalityPlan,
) -> None:
    validate_modality_plan(modality_plan, blueprint, (rlo,), _ALLOWED)


def test_minimal_valid_plan_passes(rlo: RLODocument) -> None:
    bp = _make_blueprint()
    plan = _make_plan((_make_scene(),))
    validate_modality_plan(plan, bp, (rlo,), _ALLOWED)


# ── Negative: test 7 — content not selected in blueprint ─────────────────────


def test_scene_references_unselected_component_rejected(rlo: RLODocument) -> None:
    # Blueprint selects only comp-rule-01; scene references comp-hook-01.
    bp = _make_blueprint(
        selected_content=RLOContentSelection(
            objective_ids=("lo-01",),
            component_ids=("comp-rule-01",),  # comp-hook-01 excluded
        )
    )
    plan = _make_plan((_make_scene(component_ids=("comp-hook-01",)),))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_modality_plan(plan, bp, (rlo,), _ALLOWED)
    assert exc_info.value.code == "content_not_selected"
    assert "comp-hook-01" in str(exc_info.value)


# ── Negative: test 8 — duplicate scene IDs ───────────────────────────────────


def test_duplicate_scene_ids_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint()
    plan = _make_plan((
        _make_scene(scene_id="scene-dup"),
        _make_scene(scene_id="scene-dup"),
    ))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_modality_plan(plan, bp, (rlo,), _ALLOWED)
    assert exc_info.value.code == "duplicate_id"
    assert "scene-dup" in str(exc_info.value)


# ── Negative: test 9 — unsupported modality capability ───────────────────────


def test_unsupported_preferred_capability_rejected(rlo: RLODocument) -> None:
    bp = _make_blueprint()
    plan = _make_plan((_make_scene(preferred_capability="video_render"),))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_modality_plan(plan, bp, (rlo,), _ALLOWED)
    assert exc_info.value.code == "unsupported_capability"
    assert "video_render" in str(exc_info.value)
