from dataclasses import dataclass
from typing import Any, Protocol

from learning_pipeline.contracts import (
    ListInput,
    LiteralInput,
    ObjectInput,
    TaskOutputInput,
    TaskResult,
    TaskSpec,
)


@dataclass(frozen=True)
class ExecutionContext:
    workflow_id: str
    task_id: str
    attempt: int
    inputs: dict[str, Any]


class ToolExecutor(Protocol):
    async def execute(self, context: ExecutionContext) -> dict[str, Any]: ...


class MissingTaskOutputError(KeyError):
    pass


class UnregisteredTaskTypeError(KeyError):
    pass


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, ToolExecutor] = {}

    def register(self, task_type: str, executor: ToolExecutor) -> None:
        if not task_type:
            raise ValueError("task_type must not be empty")
        if task_type in self._executors:
            raise ValueError(f"executor already registered: {task_type}")
        self._executors[task_type] = executor

    def get(self, task_type: str) -> ToolExecutor:
        try:
            return self._executors[task_type]
        except KeyError as exc:
            raise UnregisteredTaskTypeError(f"no executor registered for {task_type}") from exc

    @property
    def task_types(self) -> set[str]:
        return set(self._executors)

    @property
    def registered_task_types(self) -> frozenset[str]:
        return frozenset(self._executors)


def _resolve_binding(binding: object, results: dict[str, TaskResult], context: str) -> Any:
    """Recursively resolve a single InputBinding to its runtime value."""
    if isinstance(binding, LiteralInput):
        return binding.value
    if isinstance(binding, TaskOutputInput):
        try:
            return results[binding.task_id].outputs[binding.output_key]
        except KeyError as exc:
            raise MissingTaskOutputError(
                f"missing {binding.task_id}.{binding.output_key} for {context}"
            ) from exc
    if isinstance(binding, ListInput):
        return [_resolve_binding(item, results, context) for item in binding.items]
    if isinstance(binding, ObjectInput):
        return {
            key: _resolve_binding(val, results, context)
            for key, val in binding.fields.items()
        }
    raise TypeError(f"unsupported input binding: {type(binding).__name__}")


def resolve_task_inputs(
    task: TaskSpec,
    results: dict[str, TaskResult],
) -> dict[str, Any]:
    return {
        name: _resolve_binding(binding, results, task.id)
        for name, binding in task.inputs.items()
    }
