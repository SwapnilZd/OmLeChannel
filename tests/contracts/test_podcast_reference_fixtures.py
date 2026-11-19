"""
Reference-fixture tests for the ADKAR podcast learning journey.

Each test validates one structural property of the manually authored fixtures
that represent the expected shape of planner outputs at every contract boundary.

Validators from learning_pipeline.validation are used throughout.
No validation logic is duplicated in this file.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    LearnerContext,
    ModalityPlan,
    ModalityProductionPlan,
    RLODocument,
)
from learning_pipeline.validation import (
    InvalidRLOContentReferenceError,
    validate_build_plan,
    validate_content_selection,
    validate_modality_plan_scene_refs,
    validate_production_scene_refs,
)

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_FIXTURE_DIR = _REPO_ROOT / "examples" / "reference" / "podcast"
_RLO_PATH = _REPO_ROOT / "course-definitions" / "rlos" / "rlo-adkar-01-name-and-sequence.json"

_SUPPORTED_TASK_TYPES = {"speech.synthesize", "audio.assemble"}


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rlo() -> RLODocument:
    return RLODocument.model_validate(json.loads(_RLO_PATH.read_text()))


@pytest.fixture(scope="module")
def learner() -> LearnerContext:
    return LearnerContext.model_validate(
        json.loads((_FIXTURE_DIR / "learner_context.json").read_text())
    )


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


@pytest.fixture(scope="module")
def production_plan() -> ModalityProductionPlan:
    return ModalityProductionPlan.model_validate(
        json.loads((_FIXTURE_DIR / "production_plan.json").read_text())
    )


@pytest.fixture(scope="module")
def build_plan() -> BuildPlan:
    return BuildPlan.model_validate(
        json.loads((_FIXTURE_DIR / "build_plan.json").read_text())
    )


# ── Test 1: ADKAR RLO loads as RLODocument ────────────────────────────────────


def test_1_rlo_fixture_loads_as_rlo_document(rlo: RLODocument) -> None:
    assert rlo.id == "rlo-adkar-01-name-and-sequence"
    assert rlo.version == "1.1.0"


# ── Test 2: Learner fixture loads as LearnerContext ───────────────────────────


def test_2_learner_fixture_loads_as_learner_context(learner: LearnerContext) -> None:
    assert learner.role == "Manager"
    assert learner.deloitte_level == 55


# ── Test 3: Blueprint fixture loads as CourseBlueprint ───────────────────────


def test_3_blueprint_fixture_loads_as_course_blueprint(blueprint: CourseBlueprint) -> None:
    assert blueprint.blueprint_id == "bp-adkar-01-podcast-manager-l55"
    assert len(blueprint.ordered_rlo_refs) == 1


# ── Test 4: Modality fixture loads as ModalityPlan ───────────────────────────


def test_4_modality_fixture_loads_as_modality_plan(modality_plan: ModalityPlan) -> None:
    assert modality_plan.plan_id == "mp-adkar-01-podcast-manager-l55"
    assert len(modality_plan.scenes) == 2


# ── Test 5: Production fixture loads as ModalityProductionPlan ───────────────


def test_5_production_fixture_loads_as_production_plan(
    production_plan: ModalityProductionPlan,
) -> None:
    assert production_plan.plan_id == "pp-adkar-01-podcast-manager-l55"
    assert len(production_plan.jobs) == 3


# ── Test 6: Build fixture loads as BuildPlan ─────────────────────────────────


def test_6_build_fixture_loads_as_build_plan(build_plan: BuildPlan) -> None:
    assert build_plan.workflow_id == "workflow-adkar-01-podcast-manager-l55"
    assert len(build_plan.tasks) == 3


# ── Test 7: RLO IDs and versions agree across all fixtures ───────────────────


def test_7_rlo_id_and_version_agree_across_fixtures(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
    modality_plan: ModalityPlan,
) -> None:
    ref = blueprint.ordered_rlo_refs[0]
    assert ref.rlo_id == rlo.id
    assert ref.rlo_version == rlo.version
    assert blueprint.source_rlo_versions[rlo.id] == rlo.version

    for scene in modality_plan.scenes:
        for content_ref in scene.source_content:
            assert content_ref.rlo_id == rlo.id
            assert content_ref.rlo_version == rlo.version


# ── Test 8: All selected content IDs exist in the canonical RLO ───────────────


def test_8_selected_content_ids_exist_in_rlo(
    rlo: RLODocument,
    blueprint: CourseBlueprint,
) -> None:
    for ref in blueprint.ordered_rlo_refs:
        validate_content_selection(rlo, ref.selected_content)


# ── Test 9: Every modality-scene source reference exists in the RLO ──────────


def test_9_modality_scene_source_refs_exist_in_rlo(
    rlo: RLODocument,
    modality_plan: ModalityPlan,
) -> None:
    validate_modality_plan_scene_refs(modality_plan, (rlo,))

    valid_component_ids = {c.id for c in rlo.components}
    valid_assessment_ids = {a.id for a in rlo.assessment_items}
    valid_concept_ids = {c.id for c in rlo.concepts}
    valid_objective_ids = {rlo.enabling_objective.id}

    for scene in modality_plan.scenes:
        for ref in scene.source_content:
            for cid in ref.component_ids:
                assert cid in valid_component_ids, f"Unknown component '{cid}' in scene '{scene.id}'"
            for aid in ref.assessment_item_ids:
                assert aid in valid_assessment_ids, f"Unknown assessment '{aid}' in scene '{scene.id}'"
            for cid in ref.concept_ids:
                assert cid in valid_concept_ids, f"Unknown concept '{cid}' in scene '{scene.id}'"
            for oid in ref.objective_ids:
                assert oid in valid_objective_ids, f"Unknown objective '{oid}' in scene '{scene.id}'"


# ── Test 10: Every production-job scene reference exists in the modality plan ─


def test_10_production_job_scene_refs_exist_in_modality_plan(
    production_plan: ModalityProductionPlan,
    modality_plan: ModalityPlan,
) -> None:
    validate_production_scene_refs(production_plan, modality_plan)


# ── Test 11: Every build-plan dependency exists ───────────────────────────────


def test_11_build_plan_dependencies_exist(build_plan: BuildPlan) -> None:
    task_ids = {t.id for t in build_plan.tasks}
    for task in build_plan.tasks:
        for dep in task.depends_on:
            assert dep in task_ids, f"Task '{task.id}' depends on unknown '{dep}'"


# ── Test 12: Task-output bindings reference declared upstream outputs ─────────


def test_12_task_output_bindings_reference_declared_outputs(build_plan: BuildPlan) -> None:
    from learning_pipeline.contracts import TaskOutputInput

    tasks_by_id = {t.id: t for t in build_plan.tasks}
    for task in build_plan.tasks:
        for key, binding in task.inputs.items():
            if isinstance(binding, TaskOutputInput):
                assert binding.task_id in task.depends_on, (
                    f"Task '{task.id}' input '{key}' references '{binding.task_id}' "
                    "which is not a declared dependency"
                )
                producer = tasks_by_id[binding.task_id]
                assert binding.output_key in producer.output_keys, (
                    f"Task '{binding.task_id}' does not declare output '{binding.output_key}'"
                )


# ── Test 13: Build-plan task graph is acyclic ─────────────────────────────────


def test_13_build_plan_graph_is_acyclic(build_plan: BuildPlan) -> None:
    validate_build_plan(build_plan, _SUPPORTED_TASK_TYPES)


# ── Test 14: The two speech tasks are mutually independent ───────────────────


def test_14_speech_tasks_are_dependency_independent(build_plan: BuildPlan) -> None:
    tasks_by_id = {t.id: t for t in build_plan.tasks}
    seg1 = tasks_by_id["speech-segment-1"]
    seg2 = tasks_by_id["speech-segment-2"]
    assert "speech-segment-2" not in seg1.depends_on
    assert "speech-segment-1" not in seg2.depends_on


# ── Test 15: Podcast assembly depends on both speech tasks ───────────────────


def test_15_assembly_depends_on_both_speech_tasks(build_plan: BuildPlan) -> None:
    tasks_by_id = {t.id: t for t in build_plan.tasks}
    assembly = tasks_by_id["assemble-podcast"]
    assert "speech-segment-1" in assembly.depends_on
    assert "speech-segment-2" in assembly.depends_on


# ── Test 16: Assembly is the only deliverable task ───────────────────────────


def test_16_assembly_is_only_deliverable(build_plan: BuildPlan) -> None:
    assert build_plan.deliverable_task_ids == ("assemble-podcast",)
