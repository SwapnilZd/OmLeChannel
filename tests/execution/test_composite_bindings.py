"""
Tests for ListInput and ObjectInput composite bindings.

Covers: resolution, order preservation, recursive nested references,
static plan validation, and backward compatibility with flat bindings.
"""
from __future__ import annotations

from typing import Any

import pytest

from learning_pipeline.contracts import (
    BuildPlan,
    ListInput,
    LiteralInput,
    Modality,
    ObjectInput,
    TaskOutputInput,
)
from learning_pipeline.contracts.execution import TaskResult, TaskSpec
from learning_pipeline.runtime.execution import MissingTaskOutputError, resolve_task_inputs
from learning_pipeline.validation.build_plan import PlanValidationError, validate_build_plan


# ── Helpers ───────────────────────────────────────────────────────────────────


def _result(task_id: str, outputs: dict[str, Any]) -> TaskResult:
    return TaskResult(task_id=task_id, outputs=outputs, attempts=1)


def _spec(task_id: str, inputs: dict, depends_on: tuple = (), output_keys: tuple = ("out",)) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        task_type="test.task",
        depends_on=depends_on,
        inputs=inputs,
        output_keys=output_keys,
    )


# ── LiteralInput (existing — must stay backward-compatible) ──────────────────


def test_literal_input_resolves_unchanged() -> None:
    task = _spec("t1", {"x": LiteralInput(value=42)})
    resolved = resolve_task_inputs(task, {})
    assert resolved["x"] == 42


def test_task_output_input_resolves_from_results() -> None:
    task = _spec("t2", {"y": TaskOutputInput(task_id="t1", output_key="val")}, depends_on=("t1",))
    results = {"t1": _result("t1", {"val": "hello"})}
    resolved = resolve_task_inputs(task, results)
    assert resolved["y"] == "hello"


def test_missing_task_output_raises() -> None:
    task = _spec("t2", {"y": TaskOutputInput(task_id="t1", output_key="missing")}, depends_on=("t1",))
    results = {"t1": _result("t1", {})}
    with pytest.raises(MissingTaskOutputError):
        resolve_task_inputs(task, results)


# ── ListInput ─────────────────────────────────────────────────────────────────


def test_list_input_resolves_to_list() -> None:
    task = _spec("t1", {
        "items": ListInput(items=(LiteralInput(value="a"), LiteralInput(value="b")))
    })
    resolved = resolve_task_inputs(task, {})
    assert resolved["items"] == ["a", "b"]


def test_list_input_preserves_order() -> None:
    values = [1, 2, 3, 4, 5]
    items = tuple(LiteralInput(value=v) for v in values)
    task = _spec("t1", {"seq": ListInput(items=items)})
    resolved = resolve_task_inputs(task, {})
    assert resolved["seq"] == values


def test_list_input_resolves_task_output_items() -> None:
    task = _spec(
        "t2",
        {
            "uris": ListInput(items=(
                TaskOutputInput(task_id="s1", output_key="audio_uri"),
                TaskOutputInput(task_id="s2", output_key="audio_uri"),
            ))
        },
        depends_on=("s1", "s2"),
    )
    results = {
        "s1": _result("s1", {"audio_uri": "fake://s1.wav"}),
        "s2": _result("s2", {"audio_uri": "fake://s2.wav"}),
    }
    resolved = resolve_task_inputs(task, results)
    assert resolved["uris"] == ["fake://s1.wav", "fake://s2.wav"]


def test_list_order_is_declared_not_completion_order() -> None:
    """Order in the ListInput tuple is authoritative, regardless of result insertion order."""
    task = _spec(
        "t2",
        {
            "items": ListInput(items=(
                TaskOutputInput(task_id="s1", output_key="v"),
                TaskOutputInput(task_id="s2", output_key="v"),
            ))
        },
        depends_on=("s1", "s2"),
    )
    # s2 "finished first" — added to results dict first
    results = {
        "s2": _result("s2", {"v": "SECOND"}),
        "s1": _result("s1", {"v": "FIRST"}),
    }
    resolved = resolve_task_inputs(task, results)
    assert resolved["items"] == ["FIRST", "SECOND"]


def test_empty_list_resolves_to_empty_list() -> None:
    task = _spec("t1", {"x": ListInput(items=())})
    resolved = resolve_task_inputs(task, {})
    assert resolved["x"] == []


# ── ObjectInput ───────────────────────────────────────────────────────────────


def test_object_input_resolves_to_dict() -> None:
    task = _spec("t1", {
        "seg": ObjectInput(fields={
            "id": LiteralInput(value="seg-1"),
            "uri": LiteralInput(value="fake://seg.wav"),
        })
    })
    resolved = resolve_task_inputs(task, {})
    assert resolved["seg"] == {"id": "seg-1", "uri": "fake://seg.wav"}


def test_object_input_resolves_task_output_fields() -> None:
    task = _spec(
        "t2",
        {
            "seg": ObjectInput(fields={
                "audio_uri": TaskOutputInput(task_id="s1", output_key="audio_uri"),
                "speaker": LiteralInput(value="Host"),
            })
        },
        depends_on=("s1",),
    )
    results = {"s1": _result("s1", {"audio_uri": "artifact://speech/wf/s1.wav"})}
    resolved = resolve_task_inputs(task, results)
    assert resolved["seg"]["audio_uri"] == "artifact://speech/wf/s1.wav"
    assert resolved["seg"]["speaker"] == "Host"


# ── Nested (ListInput of ObjectInput) ─────────────────────────────────────────


def test_list_of_objects_resolves_recursively() -> None:
    task = _spec(
        "assemble",
        {
            "segments": ListInput(items=(
                ObjectInput(fields={
                    "audio_uri": TaskOutputInput(task_id="s1", output_key="audio_uri"),
                    "speaker": LiteralInput(value="Host"),
                }),
                ObjectInput(fields={
                    "audio_uri": TaskOutputInput(task_id="s2", output_key="audio_uri"),
                    "speaker": LiteralInput(value="Expert"),
                }),
            ))
        },
        depends_on=("s1", "s2"),
    )
    results = {
        "s1": _result("s1", {"audio_uri": "fake://s1.wav"}),
        "s2": _result("s2", {"audio_uri": "fake://s2.wav"}),
    }
    resolved = resolve_task_inputs(task, results)
    segments = resolved["segments"]
    assert len(segments) == 2
    assert segments[0] == {"audio_uri": "fake://s1.wav", "speaker": "Host"}
    assert segments[1] == {"audio_uri": "fake://s2.wav", "speaker": "Expert"}


# ── Static plan validation ────────────────────────────────────────────────────


def _minimal_plan(tasks: list[TaskSpec]) -> BuildPlan:
    return BuildPlan(
        workflow_id="wf-1",
        source_plan_id="sp-1",
        modality=Modality.PODCAST,
        tasks=tuple(tasks),
        deliverable_task_ids=(tasks[-1].id,),
    )


def _make_plan_with_nested_binding(*, ref_task_id: str, ref_output_key: str) -> BuildPlan:
    producer = TaskSpec(
        id="s1", task_type="test.task", depends_on=(), inputs={},
        output_keys=("audio_uri",),
    )
    consumer = TaskSpec(
        id="assemble", task_type="test.task",
        depends_on=("s1",),
        inputs={
            "segments": ListInput(items=(
                ObjectInput(fields={
                    "audio_uri": TaskOutputInput(task_id=ref_task_id, output_key=ref_output_key),
                }),
            ))
        },
        output_keys=("result",),
    )
    return _minimal_plan([producer, consumer])


def test_nested_task_output_ref_validates_successfully() -> None:
    plan = _make_plan_with_nested_binding(ref_task_id="s1", ref_output_key="audio_uri")
    validate_build_plan(plan, frozenset({"test.task"}))  # must not raise


def test_nested_missing_dependency_fails_validation() -> None:
    """A TaskOutputInput inside ListInput referencing a non-dependency must fail."""
    producer = TaskSpec(
        id="s1", task_type="test.task", depends_on=(), inputs={}, output_keys=("audio_uri",)
    )
    consumer = TaskSpec(
        id="assemble", task_type="test.task",
        depends_on=(),  # s1 NOT declared as a dependency
        inputs={
            "segments": ListInput(items=(
                ObjectInput(fields={
                    "audio_uri": TaskOutputInput(task_id="s1", output_key="audio_uri"),
                }),
            ))
        },
        output_keys=("result",),
    )
    plan = _minimal_plan([producer, consumer])
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, frozenset({"test.task"}))
    assert exc_info.value.code == "invalid_output_binding"


def test_nested_missing_output_key_fails_validation() -> None:
    """Referencing an undeclared output_key inside a nested binding must fail."""
    plan = _make_plan_with_nested_binding(ref_task_id="s1", ref_output_key="nonexistent_key")
    with pytest.raises(PlanValidationError) as exc_info:
        validate_build_plan(plan, frozenset({"test.task"}))
    assert exc_info.value.code == "invalid_output_binding"


def test_flat_task_output_binding_still_validates() -> None:
    """Existing flat TaskOutputInput bindings must still pass unchanged."""
    producer = TaskSpec(
        id="s1", task_type="test.task", depends_on=(), inputs={}, output_keys=("out",)
    )
    consumer = TaskSpec(
        id="s2", task_type="test.task",
        depends_on=("s1",),
        inputs={"x": TaskOutputInput(task_id="s1", output_key="out")},
        output_keys=("result",),
    )
    plan = _minimal_plan([producer, consumer])
    validate_build_plan(plan, frozenset({"test.task"}))  # must not raise


def test_literal_binding_is_not_validated_as_output_ref() -> None:
    """LiteralInput bindings inside nested structures must not be rejected as task refs."""
    task = TaskSpec(
        id="t1", task_type="test.task", depends_on=(), inputs={
            "cfg": ObjectInput(fields={"k": LiteralInput(value="v")})
        },
        output_keys=("result",),
    )
    plan = _minimal_plan([task])
    validate_build_plan(plan, frozenset({"test.task"}))  # must not raise
