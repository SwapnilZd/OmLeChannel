# Personalized Learning Workflow Orchestration MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MVP that invokes learning planners once, freezes and validates their production plan, and executes the resulting tool DAG asynchronously without an LLM in the runtime loop.

**Architecture:** Pluggable curriculum, modality, and workflow planners each run once: they produce a tailored course blueprint, a modality-specific scene plan, and a context-rich production plan. A deterministic compiler maps production capabilities to registered task types, validates and persists an immutable `BuildPlan`, and hands it to an `asyncio` DAG runner. The runner resolves upstream outputs, executes ready tasks concurrently, applies bounded mechanical retries, persists state, and returns a deliverable manifest; runtime repair and real vendor adapters are separate follow-on work.

**Tech Stack:** Python 3.12, Pydantic 2.x, pytest 8.x, pytest-asyncio 0.23+, standard-library `asyncio`, JSON file persistence.

## Global Constraints

- LLM-backed planners may run only inside `PlanningCoordinator.create_build_plan`; `DAGRunner` must not import or invoke planning code.
- Persist the validated `BuildPlan` before executing any tool task.
- Treat source RLOs and all public plan models as immutable Pydantic models with `extra="forbid"`.
- Represent upstream outputs with typed `TaskOutputInput` objects; do not parse string interpolation expressions at runtime.
- Reject unknown task types, missing dependencies, invalid output references, duplicate task IDs, and dependency cycles before execution.
- Run independent tasks concurrently with a configurable default concurrency of four.
- Retry executor exceptions mechanically up to the task's `max_attempts`; default to two total attempts.
- Do not replan or invoke semantic repair during execution in this MVP.
- Store every plan and run-state update atomically on the local filesystem.
- Preserve completed task results in the run snapshot so later work can add resume behavior without changing executor contracts.
- Actual HeyGen, speech, Manim, image-generation, React, and SCORM adapters are outside this MVP because their API contracts and deployment credentials are not specified.

## Acceptance Criteria

- A test proves the curriculum, modality, and workflow planners are each called exactly once for a workflow.
- The validated build plan is saved before the first executor invocation.
- Two dependency-independent tasks execute concurrently.
- A downstream task starts only after every declared dependency succeeds.
- A task-output binding resolves to the exact upstream output value.
- Cyclic, incomplete, or unsupported plans fail before any executor invocation.
- A transient executor error is retried no more than `max_attempts`.
- A permanent executor error stops downstream work and persists a failed run snapshot.
- A sample three-task workflow runs from the CLI and returns the expected concatenated deliverable.
- The runtime package has no LLM client dependency.

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, Python floor, and test dependencies |
| `src/learning_pipeline/contracts.py` | Immutable RLO, planning, task, result, and manifest contracts |
| `src/learning_pipeline/validation.py` | Static build-plan validation and stable plan hashing |
| `src/learning_pipeline/production.py` | Capability catalog and deterministic production-plan compiler |
| `src/learning_pipeline/planning.py` | Planner protocols and one-time planning coordinator |
| `src/learning_pipeline/persistence.py` | Atomic plan and run-state storage |
| `src/learning_pipeline/execution.py` | Executor protocol, registry, and task-input resolution |
| `src/learning_pipeline/runner.py` | Deterministic concurrent DAG scheduler and retry behavior |
| `src/learning_pipeline/local_executors.py` | Safe local executors used by the vertical slice |
| `src/learning_pipeline/cli.py` | Command-line entry point for executing a frozen build plan |
| `examples/sample_build_plan.json` | Complete static plan demonstrating parallel fan-out and join |
| `tests/` | Unit and end-to-end tests matching the modules above |

---

### Task 1: Bootstrap the Python Package

**Files:**
- Create: `pyproject.toml`
- Create: `src/learning_pipeline/__init__.py`
- Create: `tests/test_package.py`

**Interfaces:**
- Consumes: Python 3.12.
- Produces: importable package `learning_pipeline` with version string `0.1.0`.

- [ ] **Step 1: Write the failing package-import test**

```python
# tests/test_package.py
import learning_pipeline


def test_package_version() -> None:
    assert learning_pipeline.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_package.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'learning_pipeline'`.

- [ ] **Step 3: Add package configuration and version**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling>=1.25,<2"]
build-backend = "hatchling.build"

[project]
name = "learning-workflow-orchestration"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.8,<3"]

[project.optional-dependencies]
test = [
  "pytest>=8.2,<9",
  "pytest-asyncio>=0.23,<1",
]

[project.scripts]
learning-workflow = "learning_pipeline.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/learning_pipeline"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

```python
# src/learning_pipeline/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 4: Install the package and run the test**

Run: `python -m pip install -e '.[test]' && python -m pytest tests/test_package.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the bootstrap**

```bash
git add pyproject.toml src/learning_pipeline/__init__.py tests/test_package.py
git commit -m "chore: bootstrap learning workflow package"
```

---

### Task 2: Define Immutable Planning and Execution Contracts

**Files:**
- Create: `src/learning_pipeline/contracts.py`
- Create: `tests/test_contracts.py`

**Interfaces:**
- Consumes: Pydantic 2.x.
- Produces: `RLO`, `LearnerContext`, `CourseBlueprint`, `ModalityProductionPlan`, `BuildPlan`, `TaskSpec`, `TaskResult`, `WorkflowResult`, and typed input bindings.

- [ ] **Step 1: Write contract tests for immutability, unknown fields, and typed bindings**

```python
# tests/test_contracts.py
import pytest
from pydantic import ValidationError

from learning_pipeline.contracts import (
    BuildPlan,
    LiteralInput,
    Modality,
    TaskOutputInput,
    TaskSpec,
)


def test_build_plan_is_immutable_and_rejects_unknown_fields() -> None:
    plan = BuildPlan(
        workflow_id="wf-1",
        source_plan_id="production-1",
        modality=Modality.VIDEO,
        tasks=(
            TaskSpec(
                id="audio",
                task_type="speech.synthesize",
                inputs={"script": LiteralInput(value="hello")},
                output_keys=("audio",),
            ),
        ),
        deliverable_task_ids=("audio",),
    )

    with pytest.raises(ValidationError):
        plan.workflow_id = "changed"

    with pytest.raises(ValidationError):
        BuildPlan.model_validate({**plan.model_dump(), "unexpected": True})


def test_task_output_binding_is_structured() -> None:
    binding = TaskOutputInput(task_id="audio", output_key="timestamps")
    assert binding.kind == "task_output"
    assert binding.task_id == "audio"
```

- [ ] **Step 2: Run the contract tests to verify they fail**

Run: `python -m pytest tests/test_contracts.py -v`

Expected: FAIL because `learning_pipeline.contracts` does not exist.

- [ ] **Step 3: Implement the complete contract module**

```python
# src/learning_pipeline/contracts.py
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Modality(StrEnum):
    VIDEO = "video"
    PODCAST = "podcast"
    ELEARNING = "elearning"


class RLO(FrozenModel):
    id: str
    version: str
    title: str
    learning_objectives: tuple[str, ...]
    sections: dict[str, str]
    source_refs: tuple[str, ...] = ()


class TopicProficiency(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ContentDepth(StrEnum):
    SUMMARY = "summary"
    WORKING = "working"
    COMPREHENSIVE = "comprehensive"


PROFICIENCY_ORDER: dict[TopicProficiency, int] = {
    TopicProficiency.BEGINNER: 0,
    TopicProficiency.INTERMEDIATE: 1,
    TopicProficiency.ADVANCED: 2,
}


class LearnerContext(FrozenModel):
    role: str
    deloitte_level: Literal[25, 35, 45, 55, 65] | None = None
    default_proficiency: TopicProficiency
    topic_proficiencies: dict[str, TopicProficiency] = Field(default_factory=dict)
    goals: tuple[str, ...]
    duration_limit_minutes: int | None = None
    business_context: dict[str, str] = Field(default_factory=dict)


class TailoredRLORef(FrozenModel):
    rlo_id: str
    rlo_version: str
    order: int

    included_sections: tuple[str, ...]
    excluded_sections: tuple[str, ...] = ()

    starting_proficiency: TopicProficiency
    target_proficiency: TopicProficiency
    content_depth: ContentDepth = ContentDepth.WORKING

    role_relevance: str
    example_context: str | None = None
    personalization_rationale: str

    @model_validator(mode="after")
    def target_must_not_regress(self) -> TailoredRLORef:
        if PROFICIENCY_ORDER[self.target_proficiency] < PROFICIENCY_ORDER[self.starting_proficiency]:
            raise ValueError(
                f"target_proficiency '{self.target_proficiency}' cannot be lower than "
                f"starting_proficiency '{self.starting_proficiency}'"
            )
        return self


class CourseBlueprint(FrozenModel):
    blueprint_id: str
    learner: LearnerContext
    title: str
    learning_outcomes: tuple[str, ...]
    ordered_rlo_refs: tuple[TailoredRLORef, ...]
    prerequisite_bridges: tuple[str, ...] = ()
    brand_contract: dict[str, str] = Field(default_factory=dict)


class LiteralInput(FrozenModel):
    kind: Literal["literal"] = "literal"
    value: Any


class TaskOutputInput(FrozenModel):
    kind: Literal["task_output"] = "task_output"
    task_id: str
    output_key: str


InputBinding = Annotated[
    LiteralInput | TaskOutputInput,
    Field(discriminator="kind"),
]


class ModalityScene(FrozenModel):
    id: str
    learning_objective: str
    presentation_format: str
    content_direction: str
    target_duration_seconds: int | None = None


class ModalityPlan(FrozenModel):
    plan_id: str
    modality: Modality
    narrative: str
    scenes: tuple[ModalityScene, ...]


class ProductionJob(FrozenModel):
    id: str
    capability: str
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, InputBinding] = Field(default_factory=dict)
    output_keys: tuple[str, ...]
    max_attempts: int = Field(default=2, ge=1, le=5)


class ModalityProductionPlan(FrozenModel):
    plan_id: str
    modality: Modality
    narrative: str
    jobs: tuple[ProductionJob, ...]
    deliverable_job_ids: tuple[str, ...]


class TaskSpec(FrozenModel):
    id: str
    task_type: str
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, InputBinding] = Field(default_factory=dict)
    output_keys: tuple[str, ...]
    max_attempts: int = Field(default=2, ge=1, le=5)


class BuildPlan(FrozenModel):
    workflow_id: str
    source_plan_id: str
    modality: Modality
    tasks: tuple[TaskSpec, ...]
    deliverable_task_ids: tuple[str, ...]


class TaskResult(FrozenModel):
    task_id: str
    outputs: dict[str, Any]
    attempts: int


class WorkflowResult(FrozenModel):
    workflow_id: str
    plan_hash: str
    task_results: dict[str, TaskResult]
    deliverables: tuple[TaskResult, ...]
```

- [ ] **Step 4: Run the contract tests**

Run: `python -m pytest tests/test_contracts.py -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit the contracts**

```bash
git add src/learning_pipeline/contracts.py tests/test_contracts.py
git commit -m "feat: define immutable learning workflow contracts"
```

---

### Task 3: Validate and Hash Frozen Build Plans

**Files:**
- Create: `src/learning_pipeline/validation.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Consumes: `BuildPlan` and `set[str]` of supported task types.
- Produces: `validate_build_plan(plan, supported_task_types) -> None` and `canonical_plan_hash(plan) -> str`.

- [ ] **Step 1: Write failing tests for dependency, cycle, capability, binding, and hash validation**

```python
# tests/test_validation.py
import pytest

from learning_pipeline.contracts import BuildPlan, Modality, TaskOutputInput, TaskSpec
from learning_pipeline.validation import PlanValidationError, canonical_plan_hash, validate_build_plan


def plan_with(tasks: tuple[TaskSpec, ...]) -> BuildPlan:
    return BuildPlan(
        workflow_id="wf-1",
        source_plan_id="source-1",
        modality=Modality.ELEARNING,
        tasks=tasks,
        deliverable_task_ids=(tasks[-1].id,),
    )


@pytest.mark.parametrize(
    "tasks,error_text",
    [
        ((TaskSpec(id="a", task_type="x", depends_on=("missing",), output_keys=("v",)),), "missing dependency"),
        ((TaskSpec(id="a", task_type="x", depends_on=("b",), output_keys=("v",)), TaskSpec(id="b", task_type="x", depends_on=("a",), output_keys=("v",))), "cycle"),
        ((TaskSpec(id="a", task_type="unknown", output_keys=("v",)),), "unsupported task type"),
    ],
)
def test_invalid_plans_are_rejected(tasks: tuple[TaskSpec, ...], error_text: str) -> None:
    with pytest.raises(PlanValidationError, match=error_text):
        validate_build_plan(plan_with(tasks), {"x"})


def test_binding_must_reference_a_declared_dependency_and_output() -> None:
    tasks = (
        TaskSpec(id="a", task_type="x", output_keys=("value",)),
        TaskSpec(
            id="b",
            task_type="x",
            inputs={"input": TaskOutputInput(task_id="a", output_key="missing")},
            output_keys=("value",),
        ),
    )
    with pytest.raises(PlanValidationError, match="declared dependency"):
        validate_build_plan(plan_with(tasks), {"x"})


def test_hash_is_stable_for_the_same_plan() -> None:
    plan = plan_with((TaskSpec(id="a", task_type="x", output_keys=("value",)),))
    assert canonical_plan_hash(plan) == canonical_plan_hash(plan)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_validation.py -v`

Expected: FAIL because `learning_pipeline.validation` does not exist.

- [ ] **Step 3: Implement static validation and canonical hashing**

```python
# src/learning_pipeline/validation.py
import hashlib

from learning_pipeline.contracts import BuildPlan, TaskOutputInput


class PlanValidationError(ValueError):
    pass


def validate_build_plan(plan: BuildPlan, supported_task_types: set[str]) -> None:
    tasks_by_id = {task.id: task for task in plan.tasks}
    if len(tasks_by_id) != len(plan.tasks):
        raise PlanValidationError("duplicate task id")

    for task in plan.tasks:
        if task.task_type not in supported_task_types:
            raise PlanValidationError(f"unsupported task type: {task.task_type}")
        for dependency in task.depends_on:
            if dependency not in tasks_by_id:
                raise PlanValidationError(f"missing dependency: {dependency}")
        for binding in task.inputs.values():
            if isinstance(binding, TaskOutputInput):
                if binding.task_id not in task.depends_on:
                    raise PlanValidationError(
                        f"task {task.id} binding must reference a declared dependency"
                    )
                producer = tasks_by_id[binding.task_id]
                if binding.output_key not in producer.output_keys:
                    raise PlanValidationError(
                        f"task {binding.task_id} does not declare output {binding.output_key}"
                    )

    for deliverable_id in plan.deliverable_task_ids:
        if deliverable_id not in tasks_by_id:
            raise PlanValidationError(f"missing deliverable task: {deliverable_id}")

    indegree = {task.id: 0 for task in plan.tasks}
    children: dict[str, list[str]] = {task.id: [] for task in plan.tasks}
    for task in plan.tasks:
        for dependency in task.depends_on:
            indegree[task.id] += 1
            children[dependency].append(task.id)

    ready = [task_id for task_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        task_id = ready.pop()
        visited += 1
        for child in children[task_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(plan.tasks):
        raise PlanValidationError("dependency cycle detected")


def canonical_plan_hash(plan: BuildPlan) -> str:
    payload = plan.model_dump_json(by_alias=True, exclude_none=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run the validation tests**

Run: `python -m pytest tests/test_validation.py -v`

Expected: 5 tests PASS.

- [ ] **Step 5: Commit the validator**

```bash
git add src/learning_pipeline/validation.py tests/test_validation.py
git commit -m "feat: validate and hash frozen build plans"
```

---

### Task 4: Compile Capability-Oriented Jobs into Tool Tasks

**Files:**
- Create: `src/learning_pipeline/production.py`
- Create: `tests/test_production.py`

**Interfaces:**
- Consumes: `ModalityProductionPlan` and `CapabilityCatalog`.
- Produces: `ProductionCompiler.compile(workflow_id, production_plan) -> BuildPlan`.

- [ ] **Step 1: Write the failing compiler test**

```python
# tests/test_production.py
from learning_pipeline.contracts import LiteralInput, Modality, ModalityProductionPlan, ProductionJob
from learning_pipeline.production import CapabilityCatalog, ProductionCompiler


def test_compiler_maps_capabilities_without_changing_context() -> None:
    production_plan = ModalityProductionPlan(
        plan_id="production-1",
        modality=Modality.VIDEO,
        narrative="Narrated introduction",
        jobs=(
            ProductionJob(
                id="audio",
                capability="narration",
                inputs={"script": LiteralInput(value="Welcome")},
                output_keys=("audio", "timestamps"),
            ),
        ),
        deliverable_job_ids=("audio",),
    )
    compiler = ProductionCompiler(CapabilityCatalog({"narration": "speech.synthesize"}))

    plan = compiler.compile("wf-1", production_plan)

    assert plan.tasks[0].task_type == "speech.synthesize"
    assert plan.tasks[0].inputs["script"].value == "Welcome"
    assert plan.source_plan_id == "production-1"
```

- [ ] **Step 2: Run the compiler test to verify it fails**

Run: `python -m pytest tests/test_production.py -v`

Expected: FAIL because `learning_pipeline.production` does not exist.

- [ ] **Step 3: Implement the capability catalog and compiler**

```python
# src/learning_pipeline/production.py
from learning_pipeline.contracts import BuildPlan, ModalityProductionPlan, TaskSpec


class UnknownCapabilityError(ValueError):
    pass


class CapabilityCatalog:
    def __init__(self, mappings: dict[str, str]) -> None:
        self._mappings = dict(mappings)

    def task_type_for(self, capability: str) -> str:
        try:
            return self._mappings[capability]
        except KeyError as exc:
            raise UnknownCapabilityError(capability) from exc

    @property
    def task_types(self) -> set[str]:
        return set(self._mappings.values())


class ProductionCompiler:
    def __init__(self, catalog: CapabilityCatalog) -> None:
        self._catalog = catalog

    def compile(
        self,
        workflow_id: str,
        production_plan: ModalityProductionPlan,
    ) -> BuildPlan:
        tasks = tuple(
            TaskSpec(
                id=job.id,
                task_type=self._catalog.task_type_for(job.capability),
                depends_on=job.depends_on,
                inputs=job.inputs,
                output_keys=job.output_keys,
                max_attempts=job.max_attempts,
            )
            for job in production_plan.jobs
        )
        return BuildPlan(
            workflow_id=workflow_id,
            source_plan_id=production_plan.plan_id,
            modality=production_plan.modality,
            tasks=tasks,
            deliverable_task_ids=production_plan.deliverable_job_ids,
        )
```

- [ ] **Step 4: Run the compiler test**

Run: `python -m pytest tests/test_production.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the compiler**

```bash
git add src/learning_pipeline/production.py tests/test_production.py
git commit -m "feat: compile production capabilities into tool tasks"
```

---

### Task 5: Persist Plans and Run State Atomically

**Files:**
- Create: `src/learning_pipeline/persistence.py`
- Create: `tests/test_persistence.py`

**Interfaces:**
- Consumes: `BuildPlan`, `TaskResult`, workflow status values, and a root `Path`.
- Produces: `FilePlanStore.save/load`, `RunSnapshot`, and `FileRunStateStore.save/load`.

- [ ] **Step 1: Write failing round-trip tests**

```python
# tests/test_persistence.py
from learning_pipeline.contracts import BuildPlan, Modality, TaskResult, TaskSpec
from learning_pipeline.persistence import FilePlanStore, FileRunStateStore, RunSnapshot, TaskStatus


def test_plan_and_state_round_trip(tmp_path) -> None:
    plan = BuildPlan(
        workflow_id="wf-1",
        source_plan_id="source-1",
        modality=Modality.PODCAST,
        tasks=(TaskSpec(id="audio", task_type="speech", output_keys=("audio",)),),
        deliverable_task_ids=("audio",),
    )
    plan_store = FilePlanStore(tmp_path)
    plan_store.save(plan)
    assert plan_store.load("wf-1") == plan

    snapshot = RunSnapshot(
        workflow_id="wf-1",
        plan_hash="abc",
        statuses={"audio": TaskStatus.SUCCEEDED},
        results={"audio": TaskResult(task_id="audio", outputs={"audio": "a.wav"}, attempts=1)},
    )
    state_store = FileRunStateStore(tmp_path)
    state_store.save(snapshot)
    assert state_store.load("wf-1") == snapshot
```

- [ ] **Step 2: Run the persistence test to verify it fails**

Run: `python -m pytest tests/test_persistence.py -v`

Expected: FAIL because `learning_pipeline.persistence` does not exist.

- [ ] **Step 3: Implement atomic JSON persistence**

```python
# src/learning_pipeline/persistence.py
import os
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from learning_pipeline.contracts import BuildPlan, FrozenModel, TaskResult


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunSnapshot(FrozenModel):
    workflow_id: str
    plan_hash: str
    statuses: dict[str, TaskStatus]
    results: dict[str, TaskResult] = Field(default_factory=dict)
    failure: str | None = None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


class FilePlanStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, plan: BuildPlan) -> None:
        _atomic_write(self._root / plan.workflow_id / "plan.json", plan.model_dump_json(indent=2))

    def load(self, workflow_id: str) -> BuildPlan:
        path = self._root / workflow_id / "plan.json"
        return BuildPlan.model_validate_json(path.read_text(encoding="utf-8"))


class FileRunStateStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, snapshot: RunSnapshot) -> None:
        _atomic_write(
            self._root / snapshot.workflow_id / "run-state.json",
            snapshot.model_dump_json(indent=2),
        )

    def load(self, workflow_id: str) -> RunSnapshot:
        path = self._root / workflow_id / "run-state.json"
        return RunSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run the persistence test**

Run: `python -m pytest tests/test_persistence.py -v`

Expected: PASS.

- [ ] **Step 5: Commit persistence**

```bash
git add src/learning_pipeline/persistence.py tests/test_persistence.py
git commit -m "feat: persist workflow plans and state atomically"
```

---

### Task 6: Add Executor Registration and Runtime Input Resolution

**Files:**
- Create: `src/learning_pipeline/execution.py`
- Create: `tests/test_execution.py`

**Interfaces:**
- Consumes: `TaskSpec`, completed `TaskResult` objects, and implementations of `ToolExecutor.execute(context)`.
- Produces: `ExecutionContext`, `ExecutorRegistry`, and `resolve_task_inputs(task, results) -> dict[str, Any]`.

- [ ] **Step 1: Write failing registry and binding-resolution tests**

```python
# tests/test_execution.py
import pytest

from learning_pipeline.contracts import LiteralInput, TaskOutputInput, TaskResult, TaskSpec
from learning_pipeline.execution import ExecutorRegistry, MissingTaskOutputError, resolve_task_inputs


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
```

- [ ] **Step 2: Run the execution tests to verify they fail**

Run: `python -m pytest tests/test_execution.py -v`

Expected: FAIL because `learning_pipeline.execution` does not exist.

- [ ] **Step 3: Implement executor contracts, registry, and resolver**

```python
# src/learning_pipeline/execution.py
from dataclasses import dataclass
from typing import Any, Protocol

from learning_pipeline.contracts import LiteralInput, TaskOutputInput, TaskResult, TaskSpec


@dataclass(frozen=True)
class ExecutionContext:
    workflow_id: str
    task_id: str
    inputs: dict[str, Any]


class ToolExecutor(Protocol):
    async def execute(self, context: ExecutionContext) -> dict[str, Any]: ...


class MissingTaskOutputError(KeyError):
    pass


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, ToolExecutor] = {}

    def register(self, task_type: str, executor: ToolExecutor) -> None:
        if task_type in self._executors:
            raise ValueError(f"executor already registered: {task_type}")
        self._executors[task_type] = executor

    def get(self, task_type: str) -> ToolExecutor:
        try:
            return self._executors[task_type]
        except KeyError as exc:
            raise KeyError(f"no executor registered for {task_type}") from exc

    @property
    def task_types(self) -> set[str]:
        return set(self._executors)


def resolve_task_inputs(
    task: TaskSpec,
    results: dict[str, TaskResult],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, binding in task.inputs.items():
        if isinstance(binding, LiteralInput):
            resolved[name] = binding.value
        elif isinstance(binding, TaskOutputInput):
            try:
                resolved[name] = results[binding.task_id].outputs[binding.output_key]
            except KeyError as exc:
                raise MissingTaskOutputError(
                    f"missing {binding.task_id}.{binding.output_key} for {task.id}"
                ) from exc
        else:
            raise TypeError(f"unsupported input binding: {type(binding).__name__}")
    return resolved
```

- [ ] **Step 4: Run the execution tests**

Run: `python -m pytest tests/test_execution.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit execution contracts**

```bash
git add src/learning_pipeline/execution.py tests/test_execution.py
git commit -m "feat: register tool executors and resolve task inputs"
```

---

### Task 7: Implement the Deterministic Async DAG Runner

**Files:**
- Create: `src/learning_pipeline/runner.py`
- Create: `tests/test_runner.py`

**Interfaces:**
- Consumes: validated `BuildPlan`, `ExecutorRegistry`, `FileRunStateStore`, and `max_concurrency`.
- Produces: `DAGRunner.run(plan) -> WorkflowResult`; invokes no planning interface.

- [ ] **Step 1: Write failing tests for concurrency, dependencies, retries, and failure state**

```python
# tests/test_runner.py
import asyncio

import pytest

from learning_pipeline.contracts import BuildPlan, LiteralInput, Modality, TaskOutputInput, TaskSpec
from learning_pipeline.execution import ExecutionContext, ExecutorRegistry
from learning_pipeline.persistence import FileRunStateStore, TaskStatus
from learning_pipeline.runner import DAGRunner, WorkflowExecutionError


class RecordingExecutor:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.calls: list[str] = []

    async def execute(self, context: ExecutionContext) -> dict[str, str]:
        self.calls.append(context.task_id)
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return {"value": str(context.inputs.get("value", context.task_id))}


class FailOnceExecutor:
    def __init__(self) -> None:
        self.attempts = 0

    async def execute(self, context: ExecutionContext) -> dict[str, str]:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("transient")
        return {"value": context.task_id}


@pytest.mark.asyncio
async def test_runner_fans_out_then_joins(tmp_path) -> None:
    executor = RecordingExecutor()
    registry = ExecutorRegistry()
    registry.register("record", executor)
    plan = BuildPlan(
        workflow_id="wf-parallel",
        source_plan_id="source",
        modality=Modality.VIDEO,
        tasks=(
            TaskSpec(id="a", task_type="record", inputs={"value": LiteralInput(value="A")}, output_keys=("value",)),
            TaskSpec(id="b", task_type="record", inputs={"value": LiteralInput(value="B")}, output_keys=("value",)),
            TaskSpec(
                id="join",
                task_type="record",
                depends_on=("a", "b"),
                inputs={"value": TaskOutputInput(task_id="a", output_key="value")},
                output_keys=("value",),
            ),
        ),
        deliverable_task_ids=("join",),
    )
    runner = DAGRunner(registry, FileRunStateStore(tmp_path), max_concurrency=2)

    result = await runner.run(plan)

    assert executor.maximum_active == 2
    assert executor.calls.index("join") > executor.calls.index("a")
    assert executor.calls.index("join") > executor.calls.index("b")
    assert result.deliverables[0].outputs["value"] == "A"


@pytest.mark.asyncio
async def test_runner_retries_only_to_max_attempts(tmp_path) -> None:
    executor = FailOnceExecutor()
    registry = ExecutorRegistry()
    registry.register("flaky", executor)
    plan = BuildPlan(
        workflow_id="wf-retry",
        source_plan_id="source",
        modality=Modality.PODCAST,
        tasks=(TaskSpec(id="audio", task_type="flaky", output_keys=("value",), max_attempts=2),),
        deliverable_task_ids=("audio",),
    )
    result = await DAGRunner(registry, FileRunStateStore(tmp_path)).run(plan)
    assert executor.attempts == 2
    assert result.task_results["audio"].attempts == 2


@pytest.mark.asyncio
async def test_permanent_failure_is_persisted(tmp_path) -> None:
    class BrokenExecutor:
        async def execute(self, context: ExecutionContext) -> dict[str, str]:
            raise RuntimeError("broken")

    registry = ExecutorRegistry()
    registry.register("broken", BrokenExecutor())
    plan = BuildPlan(
        workflow_id="wf-failed",
        source_plan_id="source",
        modality=Modality.ELEARNING,
        tasks=(TaskSpec(id="render", task_type="broken", output_keys=("file",), max_attempts=1),),
        deliverable_task_ids=("render",),
    )
    store = FileRunStateStore(tmp_path)
    with pytest.raises(WorkflowExecutionError, match="render"):
        await DAGRunner(registry, store).run(plan)
    snapshot = store.load("wf-failed")
    assert snapshot.statuses["render"] == TaskStatus.FAILED
    assert snapshot.failure == "broken"
```

- [ ] **Step 2: Run the runner tests to verify they fail**

Run: `python -m pytest tests/test_runner.py -v`

Expected: FAIL because `learning_pipeline.runner` does not exist.

- [ ] **Step 3: Implement the scheduler and bounded retry loop**

```python
# src/learning_pipeline/runner.py
import asyncio

from learning_pipeline.contracts import BuildPlan, TaskResult, TaskSpec, WorkflowResult
from learning_pipeline.execution import ExecutionContext, ExecutorRegistry, resolve_task_inputs
from learning_pipeline.persistence import FileRunStateStore, RunSnapshot, TaskStatus
from learning_pipeline.validation import canonical_plan_hash, validate_build_plan


class WorkflowExecutionError(RuntimeError):
    pass


class DAGRunner:
    def __init__(
        self,
        registry: ExecutorRegistry,
        state_store: FileRunStateStore,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        self._registry = registry
        self._state_store = state_store
        self._max_concurrency = max_concurrency

    async def run(self, plan: BuildPlan) -> WorkflowResult:
        validate_build_plan(plan, self._registry.task_types)
        plan_hash = canonical_plan_hash(plan)
        pending = {task.id: task for task in plan.tasks}
        running: dict[asyncio.Task[TaskResult], str] = {}
        results: dict[str, TaskResult] = {}
        statuses = {task.id: TaskStatus.PENDING for task in plan.tasks}
        self._save(plan, plan_hash, statuses, results)

        while pending or running:
            ready_ids = sorted(
                task_id
                for task_id, task in pending.items()
                if set(task.depends_on).issubset(results)
            )
            available_slots = self._max_concurrency - len(running)
            for task_id in ready_ids[:available_slots]:
                task = pending.pop(task_id)
                statuses[task_id] = TaskStatus.RUNNING
                future = asyncio.create_task(self._execute(plan.workflow_id, task, results))
                running[future] = task_id
            self._save(plan, plan_hash, statuses, results)

            if not running and pending:
                raise WorkflowExecutionError("no runnable tasks remain")

            completed, _ = await asyncio.wait(
                running,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for future in completed:
                task_id = running.pop(future)
                try:
                    task_result = future.result()
                except Exception as exc:
                    statuses[task_id] = TaskStatus.FAILED
                    for blocked_id, blocked_task in pending.items():
                        if task_id in blocked_task.depends_on:
                            statuses[blocked_id] = TaskStatus.BLOCKED
                    self._save(plan, plan_hash, statuses, results, str(exc))
                    for other in running:
                        other.cancel()
                    await asyncio.gather(*running, return_exceptions=True)
                    raise WorkflowExecutionError(f"task {task_id} failed: {exc}") from exc
                results[task_id] = task_result
                statuses[task_id] = TaskStatus.SUCCEEDED
                self._save(plan, plan_hash, statuses, results)

        deliverables = tuple(results[task_id] for task_id in plan.deliverable_task_ids)
        return WorkflowResult(
            workflow_id=plan.workflow_id,
            plan_hash=plan_hash,
            task_results=results,
            deliverables=deliverables,
        )

    async def _execute(
        self,
        workflow_id: str,
        task: TaskSpec,
        results: dict[str, TaskResult],
    ) -> TaskResult:
        inputs = resolve_task_inputs(task, results)
        executor = self._registry.get(task.task_type)
        last_error: Exception | None = None
        for attempt in range(1, task.max_attempts + 1):
            try:
                outputs = await executor.execute(
                    ExecutionContext(workflow_id=workflow_id, task_id=task.id, inputs=inputs)
                )
                missing = set(task.output_keys) - set(outputs)
                if missing:
                    raise ValueError(f"missing declared outputs: {sorted(missing)}")
                return TaskResult(task_id=task.id, outputs=outputs, attempts=attempt)
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _save(
        self,
        plan: BuildPlan,
        plan_hash: str,
        statuses: dict[str, TaskStatus],
        results: dict[str, TaskResult],
        failure: str | None = None,
    ) -> None:
        self._state_store.save(
            RunSnapshot(
                workflow_id=plan.workflow_id,
                plan_hash=plan_hash,
                statuses=dict(statuses),
                results=dict(results),
                failure=failure,
            )
        )
```

- [ ] **Step 4: Run the runner tests**

Run: `python -m pytest tests/test_runner.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit the DAG runner**

```bash
git add src/learning_pipeline/runner.py tests/test_runner.py
git commit -m "feat: execute frozen tool plans with async dag runner"
```

---

### Task 8: Add the One-Time Planning Coordinator

**Files:**
- Create: `src/learning_pipeline/planning.py`
- Create: `tests/test_planning.py`

**Interfaces:**
- Consumes: `CurriculumPlanner`, `ModalityPlanner`, `WorkflowPlanner`, `ProductionCompiler`, `FilePlanStore`, supported task types, RLOs, learner context, and selected modality.
- Produces: `PlanningCoordinator.create_build_plan(...) -> BuildPlan`, with exactly one call to each of the three planners and plan persistence before return.

- [ ] **Step 1: Write the failing single-invocation and persistence test**

```python
# tests/test_planning.py
import pytest

from learning_pipeline.contracts import (
    CourseBlueprint,
    LearnerContext,
    LiteralInput,
    Modality,
    ModalityPlan,
    ModalityProductionPlan,
    ModalityScene,
    ProductionJob,
    RLO,
    TopicProficiency,
)
from learning_pipeline.persistence import FilePlanStore
from learning_pipeline.planning import PlanningCoordinator
from learning_pipeline.production import CapabilityCatalog, ProductionCompiler


class CountingCurriculumPlanner:
    def __init__(self, blueprint: CourseBlueprint) -> None:
        self.blueprint = blueprint
        self.calls = 0

    async def create_blueprint(self, rlos, learner) -> CourseBlueprint:
        self.calls += 1
        return self.blueprint


class CountingModalityPlanner:
    def __init__(self, modality_plan: ModalityPlan) -> None:
        self.modality_plan = modality_plan
        self.calls = 0

    async def create_modality_plan(self, blueprint, modality) -> ModalityPlan:
        self.calls += 1
        return self.modality_plan


class CountingWorkflowPlanner:
    def __init__(self, production_plan: ModalityProductionPlan) -> None:
        self.production_plan = production_plan
        self.calls = 0

    async def create_production_plan(self, modality_plan) -> ModalityProductionPlan:
        self.calls += 1
        return self.production_plan


@pytest.mark.asyncio
async def test_planners_run_once_and_plan_is_persisted(tmp_path) -> None:
    learner = LearnerContext(
        role="analyst",
        default_proficiency=TopicProficiency.BEGINNER,
        goals=("explain risk",),
    )
    blueprint = CourseBlueprint(
        blueprint_id="bp-1",
        learner=learner,
        title="Risk Basics",
        learning_outcomes=("Explain risk",),
        ordered_rlo_refs=(),
    )
    modality_plan = ModalityPlan(
        plan_id="modality-1",
        modality=Modality.PODCAST,
        narrative="Short narrated lesson",
        scenes=(
            ModalityScene(
                id="scene-1",
                learning_objective="Explain risk",
                presentation_format="narrated_explanation",
                content_direction="Define risk using an analyst example",
                target_duration_seconds=30,
            ),
        ),
    )
    production_plan = ModalityProductionPlan(
        plan_id="prod-1",
        modality=Modality.PODCAST,
        narrative="Short narrated lesson",
        jobs=(
            ProductionJob(
                id="audio",
                capability="narration",
                inputs={"script": LiteralInput(value="Risk is uncertainty.")},
                output_keys=("audio",),
            ),
        ),
        deliverable_job_ids=("audio",),
    )
    curriculum = CountingCurriculumPlanner(blueprint)
    modality = CountingModalityPlanner(modality_plan)
    workflow = CountingWorkflowPlanner(production_plan)
    store = FilePlanStore(tmp_path)
    coordinator = PlanningCoordinator(
        curriculum_planner=curriculum,
        modality_planner=modality,
        workflow_planner=workflow,
        compiler=ProductionCompiler(CapabilityCatalog({"narration": "speech.synthesize"})),
        plan_store=store,
        supported_task_types={"speech.synthesize"},
    )
    rlo = RLO(id="rlo-1", version="1", title="Risk", learning_objectives=("Explain risk",), sections={"body": "Risk is uncertainty."})

    plan = await coordinator.create_build_plan("wf-1", (rlo,), learner, Modality.PODCAST)

    assert curriculum.calls == 1
    assert modality.calls == 1
    assert workflow.calls == 1
    assert store.load("wf-1") == plan
```

- [ ] **Step 2: Run the planning test to verify it fails**

Run: `python -m pytest tests/test_planning.py -v`

Expected: FAIL because `learning_pipeline.planning` does not exist.

- [ ] **Step 3: Implement planner protocols and the coordinator**

```python
# src/learning_pipeline/planning.py
from typing import Protocol

from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    LearnerContext,
    Modality,
    ModalityPlan,
    ModalityProductionPlan,
    RLO,
)
from learning_pipeline.persistence import FilePlanStore
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.validation import validate_build_plan


class CurriculumPlanner(Protocol):
    async def create_blueprint(
        self,
        rlos: tuple[RLO, ...],
        learner: LearnerContext,
    ) -> CourseBlueprint: ...


class ModalityPlanner(Protocol):
    async def create_modality_plan(
        self,
        blueprint: CourseBlueprint,
        modality: Modality,
    ) -> ModalityPlan: ...


class WorkflowPlanner(Protocol):
    async def create_production_plan(
        self,
        modality_plan: ModalityPlan,
    ) -> ModalityProductionPlan: ...


class PlanningCoordinator:
    def __init__(
        self,
        curriculum_planner: CurriculumPlanner,
        modality_planner: ModalityPlanner,
        workflow_planner: WorkflowPlanner,
        compiler: ProductionCompiler,
        plan_store: FilePlanStore,
        supported_task_types: set[str],
    ) -> None:
        self._curriculum_planner = curriculum_planner
        self._modality_planner = modality_planner
        self._workflow_planner = workflow_planner
        self._compiler = compiler
        self._plan_store = plan_store
        self._supported_task_types = supported_task_types

    async def create_build_plan(
        self,
        workflow_id: str,
        rlos: tuple[RLO, ...],
        learner: LearnerContext,
        selected_modality: Modality,
    ) -> BuildPlan:
        blueprint = await self._curriculum_planner.create_blueprint(rlos, learner)
        modality_plan = await self._modality_planner.create_modality_plan(
            blueprint,
            selected_modality,
        )
        if modality_plan.modality != selected_modality:
            raise ValueError("modality planner changed the selected modality")
        production_plan = await self._workflow_planner.create_production_plan(modality_plan)
        if production_plan.modality != selected_modality:
            raise ValueError("workflow planner changed the selected modality")
        plan = self._compiler.compile(workflow_id, production_plan)
        validate_build_plan(plan, self._supported_task_types)
        self._plan_store.save(plan)
        return plan
```

- [ ] **Step 4: Run the planning test**

Run: `python -m pytest tests/test_planning.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the planning boundary**

```bash
git add src/learning_pipeline/planning.py tests/test_planning.py
git commit -m "feat: create and persist build plans with one-time planners"
```

---

### Task 9: Prove the Vertical Slice with Local Executors and a CLI

**Files:**
- Create: `src/learning_pipeline/local_executors.py`
- Create: `src/learning_pipeline/cli.py`
- Create: `examples/sample_build_plan.json`
- Create: `tests/test_cli.py`
- Create: `README.md`

**Interfaces:**
- Consumes: a frozen build-plan JSON path and a run-directory path.
- Produces: process exit code zero and JSON `WorkflowResult` on stdout.

- [ ] **Step 1: Write the failing CLI integration test**

```python
# tests/test_cli.py
import json
import subprocess
import sys
from pathlib import Path


def test_sample_plan_produces_joined_deliverable(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "learning_pipeline.cli",
            "examples/sample_build_plan.json",
            "--run-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["deliverables"][0]["outputs"]["text"] == "Hello world"
    assert (tmp_path / "sample-workflow" / "run-state.json").exists()
```

- [ ] **Step 2: Run the CLI test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`

Expected: FAIL because the CLI module and example plan do not exist.

- [ ] **Step 3: Implement safe local executors**

```python
# src/learning_pipeline/local_executors.py
from typing import Any

from learning_pipeline.execution import ExecutionContext


class EmitExecutor:
    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        return {"text": context.inputs["text"]}


class ConcatExecutor:
    async def execute(self, context: ExecutionContext) -> dict[str, str]:
        return {"text": f'{context.inputs["left"]}{context.inputs["right"]}'}
```

- [ ] **Step 4: Implement the CLI**

```python
# src/learning_pipeline/cli.py
import argparse
import asyncio
from pathlib import Path

from learning_pipeline.contracts import BuildPlan
from learning_pipeline.execution import ExecutorRegistry
from learning_pipeline.local_executors import ConcatExecutor, EmitExecutor
from learning_pipeline.persistence import FileRunStateStore
from learning_pipeline.runner import DAGRunner


async def _run(plan_path: Path, run_dir: Path) -> str:
    plan = BuildPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    registry = ExecutorRegistry()
    registry.register("local.emit", EmitExecutor())
    registry.register("local.concat", ConcatExecutor())
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(plan)
    return result.model_dump_json(indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    print(asyncio.run(_run(args.plan, args.run_dir)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add the complete example plan**

```json
{
  "workflow_id": "sample-workflow",
  "source_plan_id": "sample-production-plan",
  "modality": "elearning",
  "tasks": [
    {
      "id": "hello",
      "task_type": "local.emit",
      "depends_on": [],
      "inputs": {"text": {"kind": "literal", "value": "Hello "}},
      "output_keys": ["text"],
      "max_attempts": 2
    },
    {
      "id": "world",
      "task_type": "local.emit",
      "depends_on": [],
      "inputs": {"text": {"kind": "literal", "value": "world"}},
      "output_keys": ["text"],
      "max_attempts": 2
    },
    {
      "id": "join",
      "task_type": "local.concat",
      "depends_on": ["hello", "world"],
      "inputs": {
        "left": {"kind": "task_output", "task_id": "hello", "output_key": "text"},
        "right": {"kind": "task_output", "task_id": "world", "output_key": "text"}
      },
      "output_keys": ["text"],
      "max_attempts": 2
    }
  ],
  "deliverable_task_ids": ["join"]
}
```

- [ ] **Step 6: Document the architecture and explicit runtime boundary**

````markdown
# Learning Workflow Orchestration MVP

This package separates one-time learning planning from deterministic runtime execution.

1. `PlanningCoordinator` invokes the curriculum, modality, and workflow planners once.
2. `ProductionCompiler` converts capability-oriented jobs into a frozen `BuildPlan`.
3. `validate_build_plan` rejects unsafe or incomplete plans before execution.
4. `DAGRunner` executes registered tool adapters concurrently without invoking an LLM.
5. Failed tools receive bounded mechanical retries; this MVP never replans at runtime.

Run the sample:

```bash
learning-workflow examples/sample_build_plan.json --run-dir .runs
```

The CLI prints `Hello world` as the deliverable and persists the run state under `.runs/sample-workflow/`.
````

- [ ] **Step 7: Run the complete test suite and sample CLI**

Run: `python -m pytest -v`

Expected: all tests PASS.

Run: `python -m learning_pipeline.cli examples/sample_build_plan.json --run-dir /tmp/learning-workflow-runs`

Expected: exit code zero and a JSON deliverable whose `outputs.text` is `Hello world`.

- [ ] **Step 8: Commit the vertical slice**

```bash
git add src/learning_pipeline/local_executors.py src/learning_pipeline/cli.py examples/sample_build_plan.json tests/test_cli.py README.md
git commit -m "feat: demonstrate deterministic learning workflow execution"
```

---

## Final Verification Gate

- [ ] Run `python -m pytest -v` and confirm every test passes.
- [ ] Run `python -m learning_pipeline.cli examples/sample_build_plan.json --run-dir /tmp/learning-workflow-runs` and confirm the deliverable is `Hello world`.
- [ ] Run `python -m pip freeze | grep -Ei 'openai|anthropic|langchain'` and confirm it produces no output, demonstrating that runtime has no LLM SDK dependency.
- [ ] Inspect `/tmp/learning-workflow-runs/sample-workflow/run-state.json` and confirm `hello`, `world`, and `join` are `succeeded`.
- [ ] Confirm `PlanningCoordinator` is absent from imports in `src/learning_pipeline/runner.py`, `src/learning_pipeline/execution.py`, and `src/learning_pipeline/local_executors.py`.

## Follow-On Plans

Implement these as separate, independently reviewed plans after this MVP passes:

1. Provider-specific curriculum and modality planner adapters with structured-output prompts and grounding against immutable RLO source references.
2. HeyGen, speech, image-generation, Manim, React, and SCORM executor adapters, each with its own request schema, polling behavior, deterministic technical validators, and contract tests.
3. Durable distributed execution using the selected production workflow platform, including leases, idempotency keys, resume-from-snapshot behavior, cancellation, and operational dashboards.
4. Bounded semantic repair that receives only a failed task and returns a validated plan patch with a single configured repair attempt.

---

## Completed Extensions

### Extension 1 — Seniority, Proficiency, and Depth Separation (2026-07-15)

Separated learner organizational level (`deloitte_level`), per-topic knowledge (`default_proficiency` / `topic_proficiencies`), and instructional intensity (`content_depth`) as independent concepts. Added `TopicProficiency` and `ContentDepth` enums. Added `PROFICIENCY_ORDER` dict and a `model_validator` on `TailoredRLORef` that prevents `target_proficiency` from being lower than `starting_proficiency`. Added `personalization_rationale` as a required field on `TailoredRLORef`.

### Extension 2 — Modality Capability Envelope (2026-07-15)

Added a typed, request-scoped `ModalityCapabilityEnvelope` that is derived by intersecting `ModalityPolicyRegistry` (which formats each modality permits) with `FormatCapabilityMap` (which live capabilities each format requires) and the compiler's `live_capabilities`. The envelope exposes only presentation format names — no executor task types or vendor identifiers. `validate_modality_plan` rejects any scene whose format is absent from the envelope, and the coordinator calls this immediately after the modality planner returns.

### Extension 3 — Canonical RLO Model and Reference-Based Tailoring (2026-07-16)

Replaced the simplified `RLO` stub with the complete `RLODocument` model matching the versioned JSON schema in `course-definitions/rlos/`. Added all nested types (`Source`, `Misconception`, `EnablingObjective`, `Concept`, `InstructionalComponent`, `AssessmentOption`, `AssessmentItem`, `DesignBrief`, `GagneEventMapping`, `ContentTypeRecommendation`, `Governance`, `Accessibility`). `InstructionalComponent.canonical_content` accepts both string and structured-dict content.

Replaced `included_sections`/`excluded_sections` on `TailoredRLORef` with `RLOContentSelection` (reference-based overlay for objective, concept, component, and assessment item IDs). Strengthened `CourseBlueprint` with validators for unique/positive RLO orders and consistency between `source_rlo_versions` and `ordered_rlo_refs`.

Added `repository.py` with `RLORepository` (Protocol), `InMemoryRLORepository`, and typed error classes. Added `resolver.py` with `ModalityPlanningContext` (blueprint + source RLOs + modality + envelope) and `ModalityContextResolver` that loads RLOs from the repository and validates all content-selection references before the modality planner runs.

Updated `ModalityScene` to use `source_content: tuple[RLOContentRef, ...]` (non-empty), `teaching_pattern`, `preferred_capability`, and `acceptable_fallbacks`. Added `source_scene_ids` to `ProductionJob` and `validate_production_scene_refs` in `production.py`. The coordinator calls scene-ref validation before compilation.

57 tests pass. New files: `repository.py`, `resolver.py`, `tests/test_rlo_document.py`, `tests/test_resolver.py`.
