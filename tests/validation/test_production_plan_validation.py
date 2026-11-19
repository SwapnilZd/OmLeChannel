"""Tests for validate_production_plan — cross-contract production plan validation."""

from __future__ import annotations

import json
import pathlib

import pytest

from learning_pipeline.contracts import (
    LiteralInput,
    Modality,
    ModalityPlan,
    ModalityProductionPlan,
    ModalityScene,
    ProductionJob,
    RLOContentRef,
    TaskOutputInput,
)
from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.production_plan import validate_production_plan

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_FIXTURE_DIR = _REPO_ROOT / "examples" / "reference" / "podcast"

_SUPPORTED = frozenset({"narration", "audio_assembly"})


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


def _minimal_modality_plan(scene_ids: tuple[str, ...] = ("scene-a",)) -> ModalityPlan:
    scenes = tuple(
        ModalityScene(
            id=sid,
            source_content=(RLOContentRef(rlo_id="rlo-1", rlo_version="1"),),
            learning_objective="obj",
            teaching_pattern="pattern",
            preferred_capability="narration",
            content_direction="direction",
        )
        for sid in scene_ids
    )
    return ModalityPlan(
        plan_id="mp-test",
        modality=Modality.PODCAST,
        narrative="test",
        scenes=scenes,
    )


def _make_job(
    job_id: str = "job-a",
    capability: str = "narration",
    scene_ids: tuple[str, ...] = ("scene-a",),
    depends_on: tuple[str, ...] = (),
    inputs: dict | None = None,
    output_keys: tuple[str, ...] = ("audio_file",),
) -> ProductionJob:
    return ProductionJob(
        id=job_id,
        source_scene_ids=scene_ids,
        capability=capability,
        depends_on=depends_on,
        inputs=inputs or {},
        output_keys=output_keys,
    )


def _make_plan(
    jobs: tuple[ProductionJob, ...],
    deliverable_job_ids: tuple[str, ...] | None = None,
    modality: Modality = Modality.PODCAST,
) -> ModalityProductionPlan:
    if deliverable_job_ids is None:
        deliverable_job_ids = (jobs[-1].id,)
    return ModalityProductionPlan(
        plan_id="pp-test",
        modality=modality,
        narrative="test",
        jobs=jobs,
        deliverable_job_ids=deliverable_job_ids,
    )


# ── Happy path ────────────────────────────────────────────────────────────────


def test_reference_production_plan_passes(
    production_plan: ModalityProductionPlan,
    modality_plan: ModalityPlan,
) -> None:
    validate_production_plan(production_plan, modality_plan, _SUPPORTED)


def test_assembly_job_with_empty_scene_ids_passes() -> None:
    mp = _minimal_modality_plan(("scene-a", "scene-b"))
    speech_a = _make_job("speech-a", scene_ids=("scene-a",))
    speech_b = _make_job("speech-b", scene_ids=("scene-b",))
    assembly = _make_job(
        "assembly",
        capability="audio_assembly",
        scene_ids=(),  # empty is permitted by contract for assembly jobs
        depends_on=("speech-a", "speech-b"),
        inputs={
            "seg1": TaskOutputInput(task_id="speech-a", output_key="audio_file"),
            "seg2": TaskOutputInput(task_id="speech-b", output_key="audio_file"),
        },
    )
    pp = _make_plan((speech_a, speech_b, assembly))
    validate_production_plan(pp, mp, _SUPPORTED)


# ── Negative: test 10 — invalid production-job scene ID ──────────────────────


def test_invalid_scene_id_rejected(modality_plan: ModalityPlan) -> None:
    job = _make_job(scene_ids=("nonexistent-scene",))
    pp = _make_plan((job,))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, modality_plan, _SUPPORTED)
    assert exc_info.value.code == "invalid_scene_reference"
    assert "nonexistent-scene" in str(exc_info.value)


# ── Negative: test 11 — unsupported production capability ────────────────────


def test_unsupported_capability_rejected() -> None:
    mp = _minimal_modality_plan()
    job = _make_job(capability="video_render")
    pp = _make_plan((job,))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, mp, _SUPPORTED)
    assert exc_info.value.code == "unsupported_capability"
    assert "video_render" in str(exc_info.value)


# ── Negative: test 12 — missing production dependency ────────────────────────


def test_missing_dependency_rejected() -> None:
    mp = _minimal_modality_plan()
    job = _make_job(depends_on=("nonexistent-job",))
    pp = _make_plan((job,))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, mp, _SUPPORTED)
    assert exc_info.value.code == "missing_dependency"
    assert "nonexistent-job" in str(exc_info.value)


# ── Negative: test 13 — production dependency cycle ──────────────────────────


def test_production_dependency_cycle_rejected() -> None:
    mp = _minimal_modality_plan(("scene-a", "scene-b"))
    job_a = _make_job("job-a", scene_ids=("scene-a",), depends_on=("job-b",))
    job_b = _make_job("job-b", scene_ids=("scene-b",), depends_on=("job-a",))
    pp = _make_plan((job_a, job_b))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, mp, _SUPPORTED)
    assert exc_info.value.code == "dependency_cycle"


# ── Negative: test 14 — binding to a non-dependency ─────────────────────────


def test_output_binding_to_nondependency_rejected() -> None:
    mp = _minimal_modality_plan(("scene-a", "scene-b"))
    upstream = _make_job("upstream", scene_ids=("scene-a",), output_keys=("audio_file",))
    # downstream does NOT declare "upstream" in depends_on
    downstream = _make_job(
        "downstream",
        scene_ids=("scene-b",),
        depends_on=(),
        inputs={"in": TaskOutputInput(task_id="upstream", output_key="audio_file")},
    )
    pp = _make_plan((upstream, downstream))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, mp, _SUPPORTED)
    assert exc_info.value.code == "invalid_output_binding"


# ── Negative: test 15 — binding to an undeclared output ──────────────────────


def test_output_binding_to_undeclared_output_rejected() -> None:
    mp = _minimal_modality_plan(("scene-a", "scene-b"))
    upstream = _make_job("upstream", scene_ids=("scene-a",), output_keys=("audio_file",))
    downstream = _make_job(
        "downstream",
        scene_ids=("scene-b",),
        depends_on=("upstream",),
        inputs={"in": TaskOutputInput(task_id="upstream", output_key="missing_key")},
    )
    pp = _make_plan((upstream, downstream))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, mp, _SUPPORTED)
    assert exc_info.value.code == "invalid_output_binding"
    assert "missing_key" in str(exc_info.value)


# ── Negative: test 21 — missing production deliverable ───────────────────────


def test_missing_deliverable_rejected() -> None:
    mp = _minimal_modality_plan()
    job = _make_job()
    pp = _make_plan((job,), deliverable_job_ids=("nonexistent-deliverable",))
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_production_plan(pp, mp, _SUPPORTED)
    assert exc_info.value.code == "missing_deliverable"
    assert "nonexistent-deliverable" in str(exc_info.value)
