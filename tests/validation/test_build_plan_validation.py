"""Tests for validate_build_plan — Phase 3 executable task graph validation."""

from __future__ import annotations

import pytest

from learning_pipeline.contracts import (
    BuildPlan,
    Modality,
    TaskOutputInput,
    TaskSpec,
)
from learning_pipeline.validation.build_plan import PlanValidationError, validate_build_plan

_REGISTERED = frozenset({"speech.synthesize", "audio.assemble"})


def _make_plan(
    tasks: tuple[TaskSpec, ...],
    deliverable_task_ids: tuple[str, ...] | None = None,
) -> BuildPlan:
    if deliverable_task_ids is None:
        deliverable_task_ids = (tasks[-1].id,)
    return BuildPlan(
        workflow_id="wf-test",
        source_plan_id="pp-test",
        modality=Modality.PODCAST,
        tasks=tasks,
        deliverable_task_ids=deliverable_task_ids,
    )


def _task(
    task_id: str,
    task_type: str = "speech.synthesize",
    depends_on: tuple[str, ...] = (),
    output_keys: tuple[str, ...] = ("audio_file",),
    inputs: dict | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        task_type=task_type,
        depends_on=depends_on,
        output_keys=output_keys,
        inputs=inputs or {},
    )


# ── Happy path ────────────────────────────────────────────────────────────────


def test_valid_single_task_passes() -> None:
    plan = _make_plan((_task("task-a"),))
    validate_build_plan(plan, _REGISTERED)


def test_valid_two_task_chain_passes() -> None:
    a = _task("a")
    b = _task("b", task_type="audio.assemble", depends_on=("a",))
    plan = _make_plan((a, b))
    validate_build_plan(plan, _REGISTERED)


# ── Negative: test 16 — unsupported task type ────────────────────────────────


def test_unsupported_task_type_rejected() -> None:
    plan = _make_plan((_task("a", task_type="unknown.type"),))
    with pytest.raises(PlanValidationError, match="unsupported task type"):
        validate_build_plan(plan, _REGISTERED)


def test_unsupported_task_type_code() -> None:
    plan = _make_plan((_task("a", task_type="unknown.type"),))
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, _REGISTERED)
    assert exc_info.value.code == "unsupported_task_type"


# ── Negative: test 17 — missing executable dependency ────────────────────────


def test_missing_dependency_rejected() -> None:
    plan = _make_plan((_task("a", depends_on=("missing-task",)),))
    with pytest.raises(PlanValidationError, match="missing dependency"):
        validate_build_plan(plan, _REGISTERED)


def test_missing_dependency_code() -> None:
    plan = _make_plan((_task("a", depends_on=("missing-task",)),))
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, _REGISTERED)
    assert exc_info.value.code == "missing_dependency"


# ── Negative: test 18 — executable dependency cycle ──────────────────────────


def test_dependency_cycle_rejected() -> None:
    a = _task("a", depends_on=("b",))
    b = _task("b", depends_on=("a",))
    plan = _make_plan((a, b))
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_build_plan(plan, _REGISTERED)


def test_dependency_cycle_code() -> None:
    a = _task("a", depends_on=("b",))
    b = _task("b", depends_on=("a",))
    plan = _make_plan((a, b))
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, _REGISTERED)
    assert exc_info.value.code == "dependency_cycle"


# ── Negative: test 19 — binding to a non-dependency ─────────────────────────


def test_binding_to_nondependency_rejected() -> None:
    a = _task("a", output_keys=("audio_file",))
    # b does NOT declare "a" in depends_on
    b = _task(
        "b",
        depends_on=(),
        inputs={"in": TaskOutputInput(task_id="a", output_key="audio_file")},
    )
    plan = _make_plan((a, b))
    with pytest.raises(PlanValidationError, match="declared dependency"):
        validate_build_plan(plan, _REGISTERED)


def test_binding_to_nondependency_code() -> None:
    a = _task("a", output_keys=("audio_file",))
    b = _task(
        "b",
        depends_on=(),
        inputs={"in": TaskOutputInput(task_id="a", output_key="audio_file")},
    )
    plan = _make_plan((a, b))
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, _REGISTERED)
    assert exc_info.value.code == "invalid_output_binding"


# ── Negative: test 20 — binding to an undeclared output ──────────────────────


def test_binding_to_undeclared_output_rejected() -> None:
    a = _task("a", output_keys=("audio_file",))
    b = _task(
        "b",
        depends_on=("a",),
        inputs={"in": TaskOutputInput(task_id="a", output_key="missing_output")},
    )
    plan = _make_plan((a, b))
    with pytest.raises(PlanValidationError, match="does not declare output"):
        validate_build_plan(plan, _REGISTERED)


def test_binding_to_undeclared_output_code() -> None:
    a = _task("a", output_keys=("audio_file",))
    b = _task(
        "b",
        depends_on=("a",),
        inputs={"in": TaskOutputInput(task_id="a", output_key="missing_output")},
    )
    plan = _make_plan((a, b))
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, _REGISTERED)
    assert exc_info.value.code == "invalid_output_binding"


# ── Negative: test 22 — missing executable deliverable ───────────────────────


def test_missing_deliverable_rejected() -> None:
    plan = _make_plan(
        (_task("a"),),
        deliverable_task_ids=("nonexistent-task",),
    )
    with pytest.raises(PlanValidationError, match="missing deliverable task"):
        validate_build_plan(plan, _REGISTERED)


def test_missing_deliverable_code() -> None:
    plan = _make_plan(
        (_task("a"),),
        deliverable_task_ids=("nonexistent-task",),
    )
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, _REGISTERED)
    assert exc_info.value.code == "missing_deliverable"


# ── Backward compat: frozenset and set both accepted ─────────────────────────


def test_plain_set_still_accepted() -> None:
    plan = _make_plan((_task("a"),))
    validate_build_plan(plan, {"speech.synthesize"})  # type: ignore[arg-type]
