"""
DAGRunner — deterministic, fail-fast async workflow executor.

Execution policy
----------------
* The plan is validated against the registered executor types before any
  executor is invoked.  An invalid plan raises ``PlanValidationError`` and
  no executor is called.
* Tasks are dispatched concurrently up to ``max_concurrency`` using asyncio.
  A task becomes ready as soon as every declared dependency has succeeded;
  scheduling is continuous (no wave barriers).
* Each task is retried up to ``TaskSpec.max_attempts`` times on executor
  exceptions or missing declared outputs.  Input-resolution failures and
  missing executor registrations are not retried.

Fail-fast policy
----------------
When a task permanently fails (exhausts all attempts):
  1. The task is marked FAILED in the run snapshot.
  2. Every pending task that depends (directly or transitively) on the failed
     task is marked BLOCKED.
  3. Any tasks currently running are cancelled.
  4. No new tasks are scheduled.
  5. The run snapshot is persisted with the failure message.
  6. ``WorkflowExecutionError`` is raised.

Determinism guarantees
----------------------
* No LLM is called.
* No planner is invoked at runtime.
* Executors are the only components that interact with external tools.
  The runner itself is pure scheduling and state management.
* The ``BuildPlan`` is never mutated during a run.
* File persistence is temporary MVP infrastructure; databases, queues, and
  resume-from-failure are future work.
"""

from __future__ import annotations

import asyncio
import logging
import time

from llm_gateway import llm_telemetry_context
from learning_pipeline.contracts import BuildPlan, TaskResult, TaskSpec, WorkflowResult
from learning_pipeline.runtime.execution import ExecutionContext, ExecutorRegistry, resolve_task_inputs
from learning_pipeline.runtime.persistence import RunSnapshot, TaskStatus, WorkflowStatus
from learning_pipeline.validation import canonical_plan_hash, validate_build_plan

log = logging.getLogger(__name__)


class WorkflowExecutionError(RuntimeError):
    pass


class UnexpectedExecutorOutputError(ValueError):
    pass


def _exception_message(exc: BaseException) -> str:
    """Return a useful persistence/UI message even for blank exceptions."""
    return str(exc).strip() or exc.__class__.__name__


class DAGRunner:
    """
    Async DAG runner that executes a ``BuildPlan`` using registered executors.

    The runner is deterministic: given the same plan and executors it always
    produces the same result.  It does not call any LLM or planner.
    """

    def __init__(
        self,
        registry: ExecutorRegistry,
        state_store: object,  # FileRunStateStore or PostgresRunStateStore — .save() may be sync or async
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        self._registry = registry
        self._state_store = state_store
        self._max_concurrency = max_concurrency
        self._active_tasks: set[asyncio.Task[TaskResult]] = set()

    async def cancel(self) -> None:
        """Cancel and await every executor task currently owned by this runner."""
        active = tuple(self._active_tasks)
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def run(self, plan: BuildPlan) -> WorkflowResult:
        validate_build_plan(plan, self._registry.registered_task_types)
        plan_hash = canonical_plan_hash(plan)
        checkpoint = await self._load_checkpoint(plan.workflow_id, plan_hash)
        reusable_results = (
            {
                task_id: result
                for task_id, result in checkpoint.results.items()
                if task_id in {task.id for task in plan.tasks}
            }
            if checkpoint is not None
            else {}
        )
        pending = {
            task.id: task for task in plan.tasks if task.id not in reusable_results
        }
        running: dict[asyncio.Task[TaskResult], str] = {}
        results: dict[str, TaskResult] = dict(reusable_results)
        statuses = {
            task.id: (
                TaskStatus.SUCCEEDED
                if task.id in reusable_results
                else TaskStatus.PENDING
            )
            for task in plan.tasks
        }
        await self._save(plan, plan_hash, WorkflowStatus.PENDING, statuses, results)

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
                self._active_tasks.add(future)
            await self._save(plan, plan_hash, WorkflowStatus.RUNNING, statuses, results)

            if not running and pending:
                raise WorkflowExecutionError("no runnable tasks remain")

            completed, _ = await asyncio.wait(
                running,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for future in completed:
                task_id = running.pop(future)
                self._active_tasks.discard(future)
                try:
                    task_result = future.result()
                except Exception as exc:
                    failure_message = _exception_message(exc)
                    statuses[task_id] = TaskStatus.FAILED
                    for blocked_id, blocked_task in pending.items():
                        if task_id in blocked_task.depends_on:
                            statuses[blocked_id] = TaskStatus.BLOCKED
                    await self._save(
                        plan,
                        plan_hash,
                        WorkflowStatus.FAILED,
                        statuses,
                        results,
                        failure_message,
                    )
                    for other in running:
                        other.cancel()
                    await asyncio.gather(*running, return_exceptions=True)
                    raise WorkflowExecutionError(
                        f"task {task_id} failed: {failure_message}"
                    ) from exc
                results[task_id] = task_result
                statuses[task_id] = TaskStatus.SUCCEEDED

        await self._save(plan, plan_hash, WorkflowStatus.SUCCEEDED, statuses, results)
        deliverables = tuple(results[task_id] for task_id in plan.deliverable_task_ids)
        return WorkflowResult(
            workflow_id=plan.workflow_id,
            plan_hash=plan_hash,
            task_results=results,
            deliverables=deliverables,
        )

    async def _load_checkpoint(
        self, workflow_id: str, plan_hash: str
    ) -> RunSnapshot | None:
        try:
            loaded = self._state_store.load(workflow_id)  # type: ignore[union-attr]
            if asyncio.iscoroutine(loaded):
                loaded = await loaded
        except (KeyError, FileNotFoundError):
            return None
        if not isinstance(loaded, RunSnapshot) or loaded.plan_hash != plan_hash:
            return None
        return loaded

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
            attempt_started = time.perf_counter()
            log.info(
                "task phase=execute workflow_id=%s task_id=%s task_type=%s "
                "attempt=%s/%s",
                workflow_id,
                task.id,
                task.task_type,
                attempt,
                task.max_attempts,
            )
            try:
                with llm_telemetry_context(job_id=workflow_id, task_id=task.id):
                    outputs = await executor.execute(
                        ExecutionContext(
                            workflow_id=workflow_id,
                            task_id=task.id,
                            attempt=attempt,
                            inputs=inputs,
                        )
                    )
                if not isinstance(outputs, dict):
                    raise TypeError(f"executor must return a dict, got {type(outputs).__name__}")
                missing = set(task.output_keys) - set(outputs)
                if missing:
                    raise ValueError(f"missing declared outputs: {sorted(missing)}")
                # Extra outputs are allowed — executors may return rich metadata
                # alongside declared keys (e.g. usage, duration, speaker).
                log.info(
                    "task phase=succeeded workflow_id=%s task_id=%s task_type=%s "
                    "attempt=%s/%s elapsed_seconds=%.2f",
                    workflow_id,
                    task.id,
                    task.task_type,
                    attempt,
                    task.max_attempts,
                    time.perf_counter() - attempt_started,
                )
                return TaskResult(task_id=task.id, outputs=outputs, attempts=attempt)
            except Exception as exc:
                last_error = exc
                log.warning(
                    "task phase=attempt-failed workflow_id=%s task_id=%s "
                    "task_type=%s attempt=%s/%s elapsed_seconds=%.2f error=%s",
                    workflow_id,
                    task.id,
                    task.task_type,
                    attempt,
                    task.max_attempts,
                    time.perf_counter() - attempt_started,
                    _exception_message(exc),
                )
        assert last_error is not None
        raise last_error

    async def _save(
        self,
        plan: BuildPlan,
        plan_hash: str,
        workflow_status: WorkflowStatus,
        statuses: dict[str, TaskStatus],
        results: dict[str, TaskResult],
        failure: str | None = None,
    ) -> None:
        snapshot = RunSnapshot(
            workflow_id=plan.workflow_id,
            plan_hash=plan_hash,
            workflow_status=workflow_status,
            statuses=dict(statuses),
            results=dict(results),
            failure=failure,
        )
        result = self._state_store.save(snapshot)  # type: ignore[union-attr]
        if asyncio.iscoroutine(result):
            await result


WorkflowRunner = DAGRunner
