from __future__ import annotations

import asyncio
import json
from collections import Counter

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
)
from learning_pipeline.tools.elearning_bundle._authoring_client import (
    AuthoringClientError,
    AuthoringPolicyError,
    PublicationReviewResult,
    StructuredAuthoringResponse,
    StructuredReviewResponse,
)
from learning_pipeline.tools.elearning_bundle._authoring_errors import (
    AuthoringValidationError,
)
from learning_pipeline.tools.elearning_bundle.executor_real_author import (
    RealElearningCourseAuthorExecutor,
)


def _title(screen_id: str) -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="title",
        source_scene_ids=("scene-01",),
        content={
            "course_title": f"Course {screen_id}",
            "subtitle": "A concise introduction.",
            "hook": "What should you consider first?",
        },
    )


def _brief(screen_count: int) -> dict:
    return {
        "deliverable_id": "course-parallel",
        "source_plan_id": "plan-parallel",
        "resolved_context_uri": "fake://ctx/parallel.json",
        "resolved_context_sha256": "a" * 64,
        "screen_requirements": [
            {
                "kind": "authored_screen",
                "screen_id": f"screen-{index:02d}",
                "source_scene_ids": ("scene-01",),
                "screen_type": "title",
                "content_direction": "Write a concise title and hook.",
            }
            for index in range(screen_count)
        ],
    }


def _context(inputs: dict) -> ExecutionContext:
    return ExecutionContext(
        workflow_id="wf-parallel",
        task_id="author-parallel",
        attempt=1,
        inputs=inputs,
    )


def _workspace_path(tmp_path):
    return next(
        (tmp_path / "artifacts" / "elearning" / "wf-parallel").glob(
            "course-parallel-workspace-*.json"
        )
    )


class RecordingParallelClient:
    def __init__(
        self,
        *,
        fail_once: set[int] | None = None,
        omit_once: set[int] | None = None,
        cost_per_batch: float | None = None,
    ) -> None:
        self.fail_once = fail_once or set()
        self.omit_once = omit_once or set()
        self.cost_per_batch = cost_per_batch
        self.author_calls: list[int] = []
        self.completion_order: list[int] = []
        self.review_calls = 0
        self.active_calls = 0
        self.peak_active_calls = 0

    async def author(self, **kwargs):
        payload = kwargs["payload"]
        batch = int(payload["batch_contract"]["batch_number"])
        batch_count = int(payload["batch_contract"]["batch_count"])
        self.author_calls.append(batch)
        self.active_calls += 1
        self.peak_active_calls = max(self.peak_active_calls, self.active_calls)
        try:
            await asyncio.sleep((batch_count - batch + 1) * 0.005)
            if batch in self.fail_once and self.author_calls.count(batch) == 1:
                raise AuthoringClientError(f"batch {batch} failed once")
            requirements = payload["authored_screen_requirements"]
            if batch in self.omit_once and self.author_calls.count(batch) == 1:
                requirements = requirements[:-1]
            screens = tuple(
                _title(requirement["screen_id"])
                for requirement in requirements
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id=f"batch-{batch}",
                    title="Parallel Course",
                    authored_screens=screens,
                ),
                model="parallel-test",
                prompt_version="test",
                input_tokens=batch * 10,
                output_tokens=batch * 5,
                estimated_cost_usd=(
                    self.cost_per_batch
                    if self.cost_per_batch is not None
                    else batch / 10
                ),
            )
        finally:
            self.active_calls -= 1
            self.completion_order.append(batch)

    async def review(self, **kwargs):
        assert self.active_calls == 0
        self.review_calls += 1
        return StructuredReviewResponse(
            result=PublicationReviewResult(),
            model="parallel-review-test",
        )


def _executor(tmp_path, client, policy):
    store = FileArtifactStore(tmp_path / "artifacts")
    return (
        RealElearningCourseAuthorExecutor(
            artifact_store=store,
            authoring_client=client,
            policy=policy,
        ),
        store,
    )


@pytest.mark.asyncio
async def test_initial_batches_overlap_with_bounded_deterministic_merge(tmp_path):
    client = RecordingParallelClient()
    executor, store = _executor(
        tmp_path,
        client,
        AgenticExecutionPolicy(max_model_calls=6),
    )
    brief = _brief(34)

    result = await executor.execute(_context(brief))

    course = json.loads(await store.get_bytes(result["course_json_uri"]))
    assert [screen["screen_id"] for screen in course["screens"]] == [
        requirement["screen_id"] for requirement in brief["screen_requirements"]
    ]
    assert client.peak_active_calls == 3
    assert client.completion_order != sorted(client.completion_order)
    assert client.review_calls == 1
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert trace["initial_batch_mode"] == "parallel"
    assert trace["initial_batch_peak_concurrency"] == 3
    assert trace["initial_batch_elapsed_seconds"] > 0
    assert trace["model_call_count"] == 6
    assert trace["input_tokens"] == 150
    assert trace["output_tokens"] == 75
    assert trace["estimated_cost_usd"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_parallel_failure_checkpoints_siblings_and_retries_only_missing_batch(
    tmp_path,
):
    client = RecordingParallelClient(fail_once={2})
    executor, store = _executor(
        tmp_path,
        client,
        AgenticExecutionPolicy(max_model_calls=4),
    )
    brief = _brief(18)
    context = _context(brief)

    with pytest.raises(AuthoringClientError, match="batch 2 failed once"):
        await executor.execute(context)

    workspace = json.loads(_workspace_path(tmp_path).read_text())
    checkpointed_ids = {
        screen["screen_id"] for screen in workspace["draft"]["authored_screens"]
    }
    assert checkpointed_ids == {
        *(f"screen-{index:02d}" for index in range(8)),
        "screen-16",
        "screen-17",
    }

    result = await executor.execute(context)

    assert Counter(client.author_calls) == {1: 1, 2: 2, 3: 1}
    course = json.loads(await store.get_bytes(result["course_json_uri"]))
    assert len(course["screens"]) == 18
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert trace["initial_batch_mode"] == "parallel"
    assert trace["initial_batch_peak_concurrency"] == 3


@pytest.mark.asyncio
async def test_hard_usage_ceiling_uses_sequential_batch_calls(tmp_path):
    client = RecordingParallelClient(cost_per_batch=0.2)
    executor, store = _executor(
        tmp_path / "sequential",
        client,
        AgenticExecutionPolicy(max_model_calls=4, max_cost_usd=1),
    )

    result = await executor.execute(_context(_brief(18)))

    assert client.author_calls == [1, 2, 3]
    assert client.peak_active_calls == 1
    sequential_trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert sequential_trace["initial_batch_mode"] == "sequential"
    assert sequential_trace["initial_batch_peak_concurrency"] == 1

    parallel_client = RecordingParallelClient(cost_per_batch=0.2)
    parallel_executor, parallel_store = _executor(
        tmp_path / "parallel",
        parallel_client,
        AgenticExecutionPolicy(max_model_calls=4),
    )
    parallel_result = await parallel_executor.execute(_context(_brief(18)))
    parallel_trace = json.loads(
        await parallel_store.get_bytes(parallel_result["trace_uri"])
    )

    assert parallel_trace["initial_batch_mode"] == "parallel"
    for field in (
        "model_call_count",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
    ):
        assert parallel_trace[field] == sequential_trace[field]


@pytest.mark.asyncio
async def test_invalid_parallel_batch_does_not_mutate_draft_and_can_resume(tmp_path):
    client = RecordingParallelClient(omit_once={2})
    executor, store = _executor(
        tmp_path,
        client,
        AgenticExecutionPolicy(max_model_calls=5),
    )
    brief = _brief(18)
    context = _context(brief)

    with pytest.raises(AuthoringValidationError, match="omitted requested"):
        await executor.execute(context)

    workspace = json.loads(_workspace_path(tmp_path).read_text())
    checkpointed_ids = {
        screen["screen_id"] for screen in workspace["draft"]["authored_screens"]
    }
    assert not checkpointed_ids.intersection(
        f"screen-{index:02d}" for index in range(8, 16)
    )
    assert workspace["model_call_count"] == 3

    result = await executor.execute(context)

    assert Counter(client.author_calls) == {1: 1, 2: 2, 3: 1}
    course = json.loads(await store.get_bytes(result["course_json_uri"]))
    assert len(course["screens"]) == 18


@pytest.mark.asyncio
async def test_parallel_call_budget_fails_before_launch(tmp_path):
    client = RecordingParallelClient()
    executor, _ = _executor(
        tmp_path,
        client,
        AgenticExecutionPolicy(max_model_calls=5),
    )

    with pytest.raises(AuthoringPolicyError, match="model-call budget"):
        await executor.execute(_context(_brief(34)))

    assert client.author_calls == []
    assert client.review_calls == 0


@pytest.mark.asyncio
async def test_post_response_budget_failure_is_saved_in_workspace(tmp_path):
    client = RecordingParallelClient(cost_per_batch=2)
    executor, _ = _executor(
        tmp_path,
        client,
        AgenticExecutionPolicy(max_model_calls=4, max_cost_usd=1),
    )

    with pytest.raises(AuthoringPolicyError, match="cost budget"):
        await executor.execute(_context(_brief(18)))

    workspace = json.loads(_workspace_path(tmp_path).read_text())
    assert workspace["model_call_count"] == 1
    assert workspace["estimated_cost_usd"] == 2
    assert workspace["draft"] is None
