import pytest

from learning_pipeline.contracts import LiteralInput, TaskOutputInput, TaskResult, TaskSpec
from learning_pipeline.runtime.execution import MissingTaskOutputError, resolve_task_inputs


def _task(**kwargs) -> TaskSpec:
    defaults: dict = {"id": "t1", "task_type": "demo", "output_keys": ("out",)}
    defaults.update(kwargs)
    return TaskSpec(**defaults)


def _result(task_id: str, outputs: dict) -> TaskResult:
    return TaskResult(task_id=task_id, outputs=outputs, attempts=1)


def test_literal_input_resolves_to_its_value():
    task = _task(inputs={"x": LiteralInput(value=42)})
    assert resolve_task_inputs(task, {}) == {"x": 42}


def test_string_literal_resolves():
    task = _task(inputs={"scene_id": LiteralInput(value="scene-intro")})
    assert resolve_task_inputs(task, {}) == {"scene_id": "scene-intro"}


def test_task_output_input_resolves_from_completed_result():
    task = _task(
        depends_on=("upstream",),
        inputs={"audio": TaskOutputInput(task_id="upstream", output_key="audio_file")},
    )
    completed = {"upstream": _result("upstream", {"audio_file": "fake://audio/x.wav"})}
    assert resolve_task_inputs(task, completed) == {"audio": "fake://audio/x.wav"}


def test_mixed_inputs_resolve_together():
    task = _task(
        depends_on=("up",),
        inputs={
            "scene_id": LiteralInput(value="scene-1"),
            "audio": TaskOutputInput(task_id="up", output_key="audio_file"),
        },
    )
    completed = {"up": _result("up", {"audio_file": "fake://audio/x.wav"})}
    resolved = resolve_task_inputs(task, completed)
    assert resolved == {"scene_id": "scene-1", "audio": "fake://audio/x.wav"}


def test_missing_upstream_task_result_raises():
    task = _task(
        depends_on=("upstream",),
        inputs={"audio": TaskOutputInput(task_id="upstream", output_key="audio_file")},
    )
    with pytest.raises(MissingTaskOutputError):
        resolve_task_inputs(task, {})


def test_missing_output_key_in_result_raises():
    task = _task(
        depends_on=("upstream",),
        inputs={"audio": TaskOutputInput(task_id="upstream", output_key="audio_file")},
    )
    completed = {"upstream": _result("upstream", {"other_key": "value"})}
    with pytest.raises(MissingTaskOutputError):
        resolve_task_inputs(task, completed)


def test_empty_inputs_returns_empty_dict():
    task = _task(inputs={})
    assert resolve_task_inputs(task, {}) == {}
