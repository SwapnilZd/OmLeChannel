import pytest

from learning_pipeline.contracts import LiteralInput, TaskOutputInput, TaskResult, TaskSpec
from learning_pipeline.runtime.execution import ExecutorRegistry, MissingTaskOutputError, resolve_task_inputs


def test_resolver_combines_literals_and_upstream_outputs() -> None:
    task = TaskSpec(
        id="assemble",
        task_type="concat",
        depends_on=("left",),
        inputs={
            "prefix": LiteralInput(value="Course: "),
            "body": TaskOutputInput(task_id="left", output_key="text"),
        },
        output_keys=("text",),
    )
    results = {"left": TaskResult(task_id="left", outputs={"text": "Intro"}, attempts=1)}
    assert resolve_task_inputs(task, results) == {"prefix": "Course: ", "body": "Intro"}


def test_missing_runtime_output_is_rejected() -> None:
    task = TaskSpec(
        id="assemble",
        task_type="concat",
        depends_on=("left",),
        inputs={"body": TaskOutputInput(task_id="left", output_key="text")},
        output_keys=("text",),
    )
    with pytest.raises(MissingTaskOutputError):
        resolve_task_inputs(task, {"left": TaskResult(task_id="left", outputs={}, attempts=1)})


def test_registry_rejects_duplicate_task_types() -> None:
    registry = ExecutorRegistry()
    executor = object()
    registry.register("concat", executor)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("concat", executor)
