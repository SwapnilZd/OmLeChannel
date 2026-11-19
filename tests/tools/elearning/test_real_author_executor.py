"""Tests for RealElearningCourseAuthorExecutor.

All tests use FakeElearningAuthoringClient — no LLM calls.
Tests cover:
- Input validation
- Context read + SHA-256 verification
- Bounded authoring call
- Deterministic CourseContent build
- Asset materialization
- Output validation
- Idempotency cache
- Preview HTML rendering
- Authoring trace
- End-to-end with real assembler
"""
from __future__ import annotations

import json

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AgenticExecutionPolicy,
    AuthoredScreenDraft,
)
from learning_pipeline.tools.elearning_bundle._authoring_client import (
    AuthoringClientError,
    AuthoringPolicyError,
    FakeElearningAuthoringClient,
    PublicationReviewResult,
    StructuredAuthoringResponse,
    StructuredReviewResponse,
)
from learning_pipeline.tools.elearning_bundle._authoring_errors import (
    AuthoringPreflightError,
    AuthoringReviewError,
    AuthoringValidationError,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    AuthoringFinding,
    FindingOwner,
    FindingRepairability,
    FindingSeverity,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
    ElearningAuthorOutput,
    VideoSlotRequirement,
)
from learning_pipeline.tools.elearning_bundle.executor_real_author import (
    RealElearningCourseAuthorExecutor,
)
from learning_pipeline.tools.errors import InvalidToolInputError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _context(inputs: dict, wf_id: str = "wf-real-01", task_id: str = "author-real-1") -> ExecutionContext:
    return ExecutionContext(workflow_id=wf_id, task_id=task_id, attempt=1, inputs=inputs)


def _slot_req(slot_id: str = "intro-video") -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=f"screen-{slot_id}",
        slot_id=slot_id,
        source_scene_ids=(f"scene-{slot_id}",),
        title=f"Video: {slot_id}",
    )


def _authored_entry(
    screen_id: str,
    screen_type: str = "title",
    source_scenes: tuple = ("scene-01",),
) -> AuthoredScreenRequirement:
    return AuthoredScreenRequirement(
        screen_id=screen_id,
        source_scene_ids=source_scenes,
        screen_type=screen_type,
        content_direction="Write a concise title and hook.",
    )


def _slot_entry(screen_id: str, slot_id: str) -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=screen_id,
        slot_id=slot_id,
        source_scene_ids=(f"scene-{slot_id}",),
        title=f"Video: {slot_id}",
    )


def _title_draft(screen_id: str = "s-title") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="title",
        source_scene_ids=("scene-01",),
        content={
            "course_title": "Real Author Course",
            "subtitle": "A real course.",
            "hook": "Discover the concepts.",
            "metadata": {"duration": "10 min"},
        },
    )


def _objectives_draft(screen_id: str = "s-objectives") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="objectives",
        source_scene_ids=("scene-01",),
        content={
            "heading": "Learning Objectives",
            "objectives": ["Understand the framework.", "Apply the concepts."],
        },
    )


def _completion_draft(screen_id: str = "s-completion") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="completion",
        source_scene_ids=("scene-01",),
        content={
            "heading": "Module Complete",
            "message": "You completed this module.",
            "skills_reinforced": ["Core concept application"],
        },
    )


def _brief_with_slots(tmp_path, *, slot_ids: list[str] | None = None) -> dict:
    """Build a valid ElearningAuthoringBrief input dict with screen_requirements."""
    slot_ids = slot_ids or ["intro-video"]
    slot_entries = [
        {
            "kind": "video_slot",
            "screen_id": f"s-{sid}",
            "slot_id": sid,
            "source_scene_ids": (f"scene-{sid}",),
            "title": f"Video: {sid}",
        }
        for sid in slot_ids
    ]
    authored_title = {
        "kind": "authored_screen",
        "screen_id": "s-title",
        "source_scene_ids": ("scene-01",),
        "screen_type": "title",
        "content_direction": "Write a concise title.",
    }
    authored_completion = {
        "kind": "authored_screen",
        "screen_id": "s-completion",
        "source_scene_ids": ("scene-01",),
        "screen_type": "completion",
        "content_direction": "Write a completion message.",
    }
    # order: title, slot(s), completion
    screen_requirements = [authored_title] + slot_entries + [authored_completion]
    return {
        "deliverable_id": "course-real-01",
        "source_plan_id": "plan-001",
        "resolved_context_uri": "fake://ctx/001.json",
        "resolved_context_sha256": "a" * 64,
        "screen_requirements": screen_requirements,
    }


def _make_executor(
    tmp_path,
    *,
    screens: list[AuthoredScreenDraft] | None = None,
    write_preview_html: bool = False,
    fail_on_call: bool = False,
    call_count_limit: int = 0,
    policy: AgenticExecutionPolicy | None = None,
) -> tuple[RealElearningCourseAuthorExecutor, FileArtifactStore]:
    store = FileArtifactStore(tmp_path / "artifacts")
    client = FakeElearningAuthoringClient(
        screens=screens or [_title_draft("s-title"), _completion_draft("s-completion")],
        fail_on_call=fail_on_call,
        call_count_limit=call_count_limit,
    )
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=policy or AgenticExecutionPolicy(),
        write_preview_html=write_preview_html,
    )
    return executor, store


# ── Input validation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_invalid_input(tmp_path):
    executor, _ = _make_executor(tmp_path)
    ctx = _context({"deliverable_id": ""})
    with pytest.raises(InvalidToolInputError):
        await executor.execute(ctx)


@pytest.mark.asyncio
async def test_rejects_brief_without_screen_requirements(tmp_path):
    executor, _ = _make_executor(tmp_path)
    # Brief with empty screen_requirements fails validator
    ctx = _context({
        "deliverable_id": "course-no-reqs",
        "source_plan_id": "plan-001",
        "resolved_context_uri": "fake://ctx",
        "resolved_context_sha256": "a" * 64,
        "screen_requirements": [],
    })
    with pytest.raises(InvalidToolInputError, match="screen_requirements"):
        await executor.execute(ctx)


@pytest.mark.asyncio
async def test_preflight_fails_before_author_call_for_unsupported_action(tmp_path):
    executor, _ = _make_executor(tmp_path)
    brief = _brief_with_slots(tmp_path)
    brief["screen_requirements"][0]["learner_action"] = "choose"

    with pytest.raises(
        AuthoringPreflightError, match="PREFLIGHT_UNSUPPORTED_LEARNER_ACTION"
    ):
        await executor.execute(_context(brief))

    assert executor._client.call_count == 0


# ── Output contract ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_valid_author_output(tmp_path):
    executor, _ = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    output = ElearningAuthorOutput.model_validate(result)
    assert output.course_json_uri.startswith("artifact://")
    assert output.slot_report.valid is True


@pytest.mark.asyncio
async def test_course_json_is_readable_from_store(tmp_path):
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    uri = result["course_json_uri"]
    course_bytes = await store.get_bytes(uri)
    course_dict = json.loads(course_bytes)
    assert "screens" in course_dict
    assert len(course_dict["screens"]) >= 1


@pytest.mark.asyncio
async def test_video_slot_is_in_intermediate_course_json(tmp_path):
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path, slot_ids=["intro-video"]))
    result = await executor.execute(ctx)
    course_bytes = await store.get_bytes(result["course_json_uri"])
    course_dict = json.loads(course_bytes)
    slot_screens = [s for s in course_dict["screens"] if s.get("type") == "video_slot"]
    assert len(slot_screens) == 1
    assert slot_screens[0]["slot_id"] == "intro-video"


@pytest.mark.asyncio
async def test_slot_report_valid(tmp_path):
    executor, _ = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    report = result["slot_report"]
    assert report["valid"] is True
    assert not report["missing_slot_ids"]


@pytest.mark.asyncio
async def test_authored_screen_in_course(tmp_path):
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    course_bytes = await store.get_bytes(result["course_json_uri"])
    course_dict = json.loads(course_bytes)
    title_screens = [s for s in course_dict["screens"] if s.get("type") == "title"]
    assert len(title_screens) == 1


@pytest.mark.asyncio
async def test_trace_uri_is_present(tmp_path):
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    assert result["trace_uri"] is not None
    trace_bytes = await store.get_bytes(result["trace_uri"])
    trace_dict = json.loads(trace_bytes)
    assert trace_dict["workflow_id"] == "wf-real-01"
    assert trace_dict["model_call_count"] >= 1


@pytest.mark.asyncio
async def test_preview_html_not_written_by_default(tmp_path):
    executor, _ = _make_executor(tmp_path, write_preview_html=False)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    assert result["preview_html"] is None


@pytest.mark.asyncio
async def test_preview_html_written_when_enabled(tmp_path):
    executor, store = _make_executor(tmp_path, write_preview_html=True)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    assert result["preview_html"] is not None
    html_bytes = await store.get_bytes(result["preview_html"]["uri"])
    assert b"reveal" in html_bytes.lower() or b"<!doctype html" in html_bytes


# ── Client error handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_error_propagates(tmp_path):
    executor, _ = _make_executor(tmp_path, fail_on_call=True)
    ctx = _context(_brief_with_slots(tmp_path))
    with pytest.raises(AuthoringClientError):
        await executor.execute(ctx)


@pytest.mark.asyncio
async def test_semantic_review_revises_only_failing_screen(tmp_path):
    initial_title = _title_draft("s-title").model_copy(
        update={
            "content": _title_draft("s-title").content.model_copy(
                update={"hook": "Grouping the steps reduces recall load."}
            )
        }
    )
    revised_title = _title_draft("s-title").model_copy(
        update={
            "content": _title_draft("s-title").content.model_copy(
                update={"hook": "Use the groups to reconstruct the steps in order."}
            )
        }
    )
    completion = _completion_draft("s-completion")

    class ReviewingClient:
        def __init__(self):
            self.author_calls = 0
            self.patch_calls = 0
            self.review_calls = 0
            self.reviewed_screen_ids = []
            self.reviewed_content_fields = []

        async def author(self, **kwargs):
            self.author_calls += 1
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id=f"draft-{self.author_calls}",
                    title="Course",
                    authored_screens=(initial_title, completion),
                ),
                model="review-test",
                prompt_version="course_author_v1",
            )

        async def patch(self, **kwargs):
            self.patch_calls += 1
            assert kwargs["payload"]["revision_contract"]["editable_field_paths"] == [
                "content.hook"
            ]
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id="patched-1",
                    title="Course",
                    authored_screens=(revised_title,),
                ),
                model="review-test",
                prompt_version="course_author_v1",
            )

        async def review(self, **kwargs):
            self.review_calls += 1
            self.reviewed_screen_ids.append(
                [
                    screen["screen_id"]
                    for screen in kwargs["payload"]["learner_view"]
                ]
            )
            self.reviewed_content_fields.append(
                [
                    sorted(screen["learner_visible_content"])
                    for screen in kwargs["payload"]["learner_view"]
                ]
            )
            findings = ()
            if self.review_calls == 1:
                findings = (
                    AuthoringFinding(
                        finding_id="leak-1",
                        code="PEDAGOGICAL_RATIONALE_LEAKAGE",
                        screen_id="s-title",
                        category="internal_rationale",
                        severity=FindingSeverity.BLOCKING,
                        owner=FindingOwner.AUTHOR,
                        repairability=FindingRepairability.AUTHOR_PATCH,
                        field_path="content.hook",
                        message="Internal learning rationale is learner-facing.",
                        evidence="reduces recall load",
                        revision_instruction="State the learner task directly.",
                    ),
                    AuthoringFinding(
                        finding_id="slot-1",
                        code="VIDEO_SLOT_REVIEW_SCOPE",
                        screen_id="s-intro-video",
                        category="video_slot",
                        severity=FindingSeverity.BLOCKING,
                        owner=FindingOwner.RENDERER,
                        repairability=FindingRepairability.AUTOMATIC,
                        message="Video-slot finding is outside authoring scope.",
                        revision_instruction="Defer to the video executor.",
                    ),
                )
            return StructuredReviewResponse(
                result=PublicationReviewResult(findings=findings),
                model="review-test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = ReviewingClient()
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_model_calls=4, max_internal_tool_calls=12),
    )
    result = await executor.execute(_context(_brief_with_slots(tmp_path)))
    course = json.loads(await store.get_bytes(result["course_json_uri"]))
    title = next(screen for screen in course["screens"] if screen["type"] == "title")
    assert title["hook"] == "Use the groups to reconstruct the steps in order."
    assert client.author_calls == 1
    assert client.patch_calls == 1
    assert client.review_calls == 2
    assert client.reviewed_screen_ids == [
        ["s-title", "s-completion"],
        ["s-title"],
    ]
    assert client.reviewed_content_fields[1] == [
        ["course_title", "hook", "subtitle"]
    ]
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert trace["revision_count"] == 1
    assert trace["review_status"] == "ready"
    assert trace["review_findings"] == [
        "Internal learning rationale is learner-facing."
    ]
    assert trace["finding_counts_by_owner"] == {"author": 1}
    assert trace["finding_counts_by_code"] == {
        "PEDAGOGICAL_RATIONALE_LEAKAGE": 1
    }
    assert trace["repair_outcomes"] == ["revision-1:resolved"]
    assert trace["elapsed_seconds"] >= 0


@pytest.mark.asyncio
async def test_no_op_patch_stops_before_another_review(tmp_path):
    title = _title_draft("s-title")
    completion = _completion_draft("s-completion")

    class NoOpPatchClient:
        def __init__(self):
            self.patch_calls = 0
            self.review_calls = 0

        async def author(self, **_kwargs):
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id="initial",
                    title="Course",
                    authored_screens=(title, completion),
                ),
                model="test",
                prompt_version="test",
            )

        async def patch(self, **_kwargs):
            self.patch_calls += 1
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id="unchanged",
                    title="Course",
                    authored_screens=(title,),
                ),
                model="test",
                prompt_version="test",
            )

        async def review(self, **_kwargs):
            self.review_calls += 1
            return StructuredReviewResponse(
                result=PublicationReviewResult(
                    findings=(
                        AuthoringFinding(
                            finding_id="no-op",
                            code="LEARNER_INSTRUCTION_UNUSABLE",
                            screen_id="s-title",
                            category="publishability",
                            severity=FindingSeverity.BLOCKING,
                            owner=FindingOwner.AUTHOR,
                            repairability=FindingRepairability.AUTHOR_PATCH,
                            field_path="content.hook",
                            message="The hook does not state a learner task.",
                            evidence="What will you discover?",
                            revision_instruction="State the learner task directly.",
                        ),
                    )
                ),
                model="test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = NoOpPatchClient()
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_model_calls=5, max_repair_attempts=2),
    )

    with pytest.raises(AuthoringValidationError, match="made no change"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))
    assert client.patch_calls == 1
    assert client.review_calls == 1


@pytest.mark.asyncio
async def test_repeated_blocking_finding_stops_without_second_patch(tmp_path):
    initial = _title_draft("s-title")
    revised = initial.model_copy(
        update={
            "content": initial.content.model_copy(
                update={"hook": "Choose the next action from the source."}
            )
        }
    )
    completion = _completion_draft("s-completion")

    class RepeatedFindingClient:
        def __init__(self):
            self.patch_calls = 0
            self.review_calls = 0

        async def author(self, **_kwargs):
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id="initial",
                    title="Course",
                    authored_screens=(initial, completion),
                ),
                model="test",
                prompt_version="test",
            )

        async def patch(self, **_kwargs):
            self.patch_calls += 1
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id="revised",
                    title="Course",
                    authored_screens=(revised,),
                ),
                model="test",
                prompt_version="test",
            )

        async def review(self, **_kwargs):
            self.review_calls += 1
            return StructuredReviewResponse(
                result=PublicationReviewResult(
                    findings=(
                        AuthoringFinding(
                            finding_id="repeat-hook-task",
                            code="LEARNER_INSTRUCTION_UNUSABLE",
                            screen_id="s-title",
                            category="publishability",
                            severity=FindingSeverity.BLOCKING,
                            owner=FindingOwner.AUTHOR,
                            repairability=FindingRepairability.AUTHOR_PATCH,
                            field_path="content.hook",
                            message="The hook still does not state the required task.",
                            evidence="Visible hook text",
                            revision_instruction="State the learner task directly.",
                        ),
                    )
                ),
                model="test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = RepeatedFindingClient()
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_model_calls=6, max_repair_attempts=2),
    )

    with pytest.raises(AuthoringPolicyError, match="repeated blocking findings"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))
    assert client.patch_calls == 1
    assert client.review_calls == 2


@pytest.mark.asyncio
async def test_distinct_same_field_finding_can_receive_second_patch(tmp_path):
    initial = _title_draft("s-title")
    first_revision = initial.model_copy(
        update={
            "content": initial.content.model_copy(
                update={"hook": "Choose the next action from the source."}
            )
        }
    )
    second_revision = initial.model_copy(
        update={
            "content": initial.content.model_copy(
                update={
                    "hook": "Choose the next source-supported action for the scenario."
                }
            )
        }
    )
    completion = _completion_draft("s-completion")

    class DistinctFindingClient:
        def __init__(self):
            self.patch_calls = 0
            self.review_calls = 0

        async def author(self, **_kwargs):
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )

            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id="initial",
                    title="Course",
                    authored_screens=(initial, completion),
                ),
                model="test",
                prompt_version="test",
            )

        async def patch(self, **_kwargs):
            self.patch_calls += 1
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )

            revised = first_revision if self.patch_calls == 1 else second_revision
            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id=f"revised-{self.patch_calls}",
                    title="Course",
                    authored_screens=(revised,),
                ),
                model="test",
                prompt_version="test",
            )

        async def review(self, **_kwargs):
            self.review_calls += 1
            findings = ()
            if self.review_calls <= 2:
                finding_id, message = (
                    (
                        "hook-missing-task",
                        "The hook does not identify a learner task.",
                    )
                    if self.review_calls == 1
                    else (
                        "hook-missing-context",
                        "The hook does not identify the scenario context.",
                    )
                )
                findings = (
                    AuthoringFinding(
                        finding_id=finding_id,
                        code="LEARNER_INSTRUCTION_UNUSABLE",
                        screen_id="s-title",
                        category="publishability",
                        severity=FindingSeverity.BLOCKING,
                        owner=FindingOwner.AUTHOR,
                        repairability=FindingRepairability.AUTHOR_PATCH,
                        field_path="content.hook",
                        message=message,
                        evidence="Visible hook text",
                        revision_instruction="Revise the hook as directed.",
                    ),
                )
            return StructuredReviewResponse(
                result=PublicationReviewResult(findings=findings),
                model="test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = DistinctFindingClient()
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_model_calls=7, max_repair_attempts=2),
    )

    result = await executor.execute(_context(_brief_with_slots(tmp_path)))

    assert client.patch_calls == 2
    assert client.review_calls == 3
    course = json.loads(await store.get_bytes(result["course_json_uri"]))
    title = next(screen for screen in course["screens"] if screen["type"] == "title")
    assert title["hook"] == "Choose the next source-supported action for the scenario."


@pytest.mark.asyncio
async def test_semantic_reviewer_cannot_route_builder_failure_to_author(tmp_path):
    class MisroutedReviewClient(FakeElearningAuthoringClient):
        async def review(self, **_kwargs):
            return StructuredReviewResponse(
                result=PublicationReviewResult(
                    findings=(
                        AuthoringFinding(
                            finding_id="misrouted-1",
                            code="LAYOUT_STRUCTURE_INVALID",
                            screen_id="s-title",
                            category="layout",
                            severity=FindingSeverity.BLOCKING,
                            owner=FindingOwner.BUILDER,
                            repairability=FindingRepairability.AUTOMATIC,
                            message="A structural layout value is invalid.",
                        ),
                    )
                ),
                model="review-test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = MisroutedReviewClient(
        screens=[_title_draft("s-title"), _completion_draft("s-completion")]
    )
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
    )

    with pytest.raises(AuthoringReviewError, match="outside the author's repair"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))

    assert client.call_count == 1


@pytest.mark.asyncio
async def test_semantic_style_preference_is_advisory_and_does_not_trigger_repair(
    tmp_path,
):
    class StyleReviewClient(FakeElearningAuthoringClient):
        def __init__(self):
            super().__init__(
                screens=[_title_draft("s-title"), _completion_draft("s-completion")]
            )
            self.review_calls = 0

        async def review(self, **_kwargs):
            self.review_calls += 1
            return StructuredReviewResponse(
                result=PublicationReviewResult(
                    findings=(
                        AuthoringFinding(
                            finding_id="style-1",
                            code="UNNECESSARY_REPETITION",
                            screen_id="s-title",
                            category="style",
                            severity=FindingSeverity.BLOCKING,
                            owner=FindingOwner.AUTHOR,
                            repairability=FindingRepairability.AUTHOR_PATCH,
                            field_path="content.hook",
                            message="The wording could be tighter.",
                            evidence="Discover the concepts.",
                            revision_instruction="Use fewer words.",
                        ),
                    )
                ),
                model="review-test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = StyleReviewClient()
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
    )

    result = await executor.execute(_context(_brief_with_slots(tmp_path)))
    trace = json.loads(await store.get_bytes(result["trace_uri"]))

    assert client.call_count == 1
    assert client.review_calls == 1
    assert trace["repair_attempt_count"] == 0


@pytest.mark.asyncio
async def test_semantic_reviewer_cannot_block_on_protected_field(tmp_path):
    class ProtectedFieldReviewClient(FakeElearningAuthoringClient):
        async def review(self, **_kwargs):
            return StructuredReviewResponse(
                result=PublicationReviewResult(
                    findings=(
                        AuthoringFinding(
                            finding_id="protected-1",
                            code="SOURCE_FIDELITY",
                            screen_id="s-title",
                            category="source_fidelity",
                            severity=FindingSeverity.BLOCKING,
                            owner=FindingOwner.AUTHOR,
                            repairability=FindingRepairability.AUTHOR_PATCH,
                            field_path="content.metadata",
                            message="The duration metadata differs from source.",
                            evidence="Duration metadata is system-derived.",
                            revision_instruction="Change the duration metadata.",
                        ),
                    )
                ),
                model="review-test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = ProtectedFieldReviewClient(
        screens=[_title_draft("s-title"), _completion_draft("s-completion")]
    )
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
    )

    with pytest.raises(AuthoringReviewError, match="protected or unknown field_path"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))

    assert client.call_count == 1


@pytest.mark.asyncio
async def test_completed_workspace_is_reused_without_model_call(tmp_path):
    executor, _ = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    await executor.execute(ctx)
    assert executor._client.call_count == 1
    await executor.execute(ctx)
    assert executor._client.call_count == 1


@pytest.mark.asyncio
async def test_large_course_is_authored_in_checkpointed_screen_batches(tmp_path):
    screen_ids = tuple(f"s-title-{index:02d}" for index in range(10))
    brief = {
        "deliverable_id": "course-batched",
        "source_plan_id": "plan-batched",
        "resolved_context_uri": "fake://ctx/batched.json",
        "resolved_context_sha256": "a" * 64,
        "screen_requirements": [
            {
                "kind": "authored_screen",
                "screen_id": screen_id,
                "source_scene_ids": ("scene-01",),
                "screen_type": "title",
                "content_direction": "Write a concise title and hook.",
            }
            for screen_id in screen_ids
        ],
    }
    executor, store = _make_executor(
        tmp_path,
        screens=[_title_draft(screen_id) for screen_id in screen_ids],
        policy=AgenticExecutionPolicy(max_model_calls=4),
    )

    result = await executor.execute(_context(brief, wf_id="wf-batched"))

    assert executor._client.call_count == 2
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert trace["authored_screen_ids"] == list(screen_ids)
    checkpoints = list(
        (tmp_path / "artifacts" / "elearning" / "wf-batched").glob(
            "course-batched-workspace-*.json"
        )
    )
    assert len(checkpoints) == 1


@pytest.mark.asyncio
async def test_corrupt_workspace_is_ignored_and_regenerated(tmp_path):
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    await executor.execute(ctx)
    workspace = next(
        (tmp_path / "artifacts" / "elearning" / "wf-real-01").glob(
            "course-real-01-workspace-*.json"
        )
    )
    workspace.write_text("{not-json", encoding="utf-8")

    result = await executor.execute(ctx)
    assert executor._client.call_count == 2
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert trace["checkpoint_recovery_events"] == ["corrupt-checkpoint-ignored"]


@pytest.mark.asyncio
async def test_incompatible_workspace_is_ignored_and_regenerated(tmp_path):
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    await executor.execute(ctx)
    workspace = next(
        (tmp_path / "artifacts" / "elearning" / "wf-real-01").glob(
            "course-real-01-workspace-*.json"
        )
    )
    data = json.loads(workspace.read_text(encoding="utf-8"))
    data["workspace_version"] = "obsolete-workspace"
    workspace.write_text(json.dumps(data), encoding="utf-8")

    result = await executor.execute(ctx)
    assert executor._client.call_count == 2
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert trace["checkpoint_recovery_events"] == [
        "incompatible-checkpoint-ignored"
    ]


@pytest.mark.asyncio
async def test_changed_input_does_not_reuse_workspace(tmp_path):
    executor, _ = _make_executor(tmp_path)
    first = _brief_with_slots(tmp_path)
    await executor.execute(_context(first))
    changed = {**first, "authoring_direction": "Use a different approved emphasis."}
    await executor.execute(_context(changed))
    assert executor._client.call_count == 2


@pytest.mark.asyncio
async def test_internal_tool_budget_fails_before_model_call(tmp_path):
    executor, _ = _make_executor(
        tmp_path,
        policy=AgenticExecutionPolicy(max_internal_tool_calls=2),
    )
    with pytest.raises(AuthoringPolicyError, match="internal-tool budget"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))
    assert executor._client.call_count == 0


@pytest.mark.asyncio
async def test_authoring_reserves_model_capacity_for_required_review(tmp_path):
    class ReviewCapableClient(FakeElearningAuthoringClient):
        async def review(self, **kwargs):
            return StructuredReviewResponse(
                result=PublicationReviewResult(findings=()),
                model="review-test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = ReviewCapableClient(
        screens=[_title_draft("s-title"), _completion_draft("s-completion")]
    )
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_model_calls=1),
    )

    with pytest.raises(AuthoringPolicyError, match="model-call budget"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))
    assert client.call_count == 0


@pytest.mark.asyncio
async def test_input_token_budget_is_cumulative_and_fail_closed(tmp_path):
    class UsageClient(FakeElearningAuthoringClient):
        async def author(self, **kwargs):
            response = await super().author(**kwargs)
            return StructuredAuthoringResponse(
                draft=response.draft,
                model=response.model,
                prompt_version=response.prompt_version,
                input_tokens=101,
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = UsageClient(
        screens=[_title_draft("s-title"), _completion_draft("s-completion")]
    )
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_input_tokens=100),
    )
    with pytest.raises(AuthoringPolicyError, match="input-token budget"):
        await executor.execute(_context(_brief_with_slots(tmp_path)))


@pytest.mark.asyncio
async def test_resume_after_failed_revision_reuses_review_checkpoint(tmp_path):
    initial = _title_draft("s-title")
    revised = initial.model_copy(
        update={
            "content": initial.content.model_copy(
                update={"hook": "Use the sequence to identify the next element."}
            )
        }
    )
    completion = _completion_draft("s-completion")

    class InterruptedRevisionClient:
        def __init__(self):
            self.author_calls = 0
            self.review_calls = 0

        async def author(self, **kwargs):
            self.author_calls += 1
            if self.author_calls == 2:
                raise AuthoringClientError("transient revision failure")
            from learning_pipeline.tools.elearning_bundle._author_contracts import (
                ElearningCourseAuthorDraft,
            )

            return StructuredAuthoringResponse(
                draft=ElearningCourseAuthorDraft(
                    draft_id=f"resume-{self.author_calls}",
                    title="Course",
                    authored_screens=(
                        initial if self.author_calls == 1 else revised,
                        completion,
                    ),
                ),
                model="resume-test",
                prompt_version="course_author_v1",
            )

        async def review(self, **kwargs):
            self.review_calls += 1
            findings = ()
            if self.review_calls == 1:
                findings = (
                    AuthoringFinding(
                        finding_id="resume-finding",
                            code="LEARNER_INSTRUCTION_UNUSABLE",
                        screen_id="s-title",
                        category="publishability",
                        severity=FindingSeverity.BLOCKING,
                        owner=FindingOwner.AUTHOR,
                        repairability=FindingRepairability.AUTHOR_PATCH,
                            field_path="content.hook",
                            message="Revise the title hook.",
                            evidence="Discover the concepts.",
                            revision_instruction="State the learner task directly.",
                    ),
                )
            return StructuredReviewResponse(
                result=PublicationReviewResult(findings=findings),
                model="resume-test",
            )

    store = FileArtifactStore(tmp_path / "artifacts")
    client = InterruptedRevisionClient()
    executor = RealElearningCourseAuthorExecutor(
        artifact_store=store,
        authoring_client=client,
        policy=AgenticExecutionPolicy(max_model_calls=4),
    )
    ctx = _context(_brief_with_slots(tmp_path))
    with pytest.raises(AuthoringClientError, match="transient revision failure"):
        await executor.execute(ctx)

    result = await executor.execute(ctx)
    assert client.author_calls == 3
    assert client.review_calls == 2
    trace = json.loads(await store.get_bytes(result["trace_uri"]))
    assert "reviewed" in trace["checkpoint_stages_reused"]
    assert "review-r1" in trace["checkpoint_stages_reused"]
    assert trace["revision_count"] == 1


# ── Screen order ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screen_order_matches_requirements(tmp_path):
    """Screens in course JSON follow requirement tuple order (title, slot, completion)."""
    executor, store = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path, slot_ids=["intro-video"]))
    result = await executor.execute(ctx)
    course_bytes = await store.get_bytes(result["course_json_uri"])
    course_dict = json.loads(course_bytes)
    types = [s["type"] for s in course_dict["screens"]]
    assert types == ["title", "video_slot", "completion"]


# ── Asset materialization ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assets_field_is_tuple(tmp_path):
    executor, _ = _make_executor(tmp_path)
    ctx = _context(_brief_with_slots(tmp_path))
    result = await executor.execute(ctx)
    assert isinstance(result["assets"], (list, tuple))


# ── End-to-end: real author → real assembler ──────────────────────────────────


@pytest.mark.asyncio
async def test_real_author_output_feeds_real_assembler(tmp_path):
    """Full pipeline: fake authoring client → real builder → real assembler.

    Verifies the real executor's output satisfies the assembler's input contract.
    No LLM, Manim, or HeyGen calls.
    """
    from learning_pipeline.runtime.artifact_store import FileArtifactStore
    from learning_pipeline.tools.elearning_bundle.contracts import (
        BundleAssetRef,
        ElearningBundleAssemblyInput,
        VideoInsertion,
    )
    from learning_pipeline.tools.elearning_bundle.executor_bundle import (
        RealElearningBundleAssemblerExecutor,
    )
    from learning_pipeline.tools.elearning_bundle.executor_fake_manim import (
        FakeManimVideoExecutor,
    )

    artifact_root = tmp_path / "artifacts"
    store = FileArtifactStore(artifact_root)

    # Step 1: run real author (fake client)
    executor, _ = _make_executor(tmp_path)
    executor._store = store  # share same store

    ctx = _context(_brief_with_slots(tmp_path, slot_ids=["intro-video"]))
    author_result = await executor.execute(ctx)

    # Step 2: run fake Manim
    manim_executor = FakeManimVideoExecutor(artifact_store=store)
    manim_ctx = ExecutionContext(
        workflow_id="wf-real-01",
        task_id="manim-1",
        attempt=1,
        inputs={
            "animation_id": "intro-video",
            "source_scene_ids": ("scene-intro-video",),
            "learning_objective": "Understand the concept.",
            "teaching_purpose": "Visual illustration.",
            "visual_direction": "Flat design.",
            "narration_script": "This is the synchronized test narration.",
            "resolved_context_uri": "fake://ctx/001.json",
            "resolved_context_sha256": "a" * 64,
        },
    )
    manim_result = await manim_executor.execute(manim_ctx)

    # Step 3: assemble
    assembler = RealElearningBundleAssemblerExecutor(artifact_store=store)
    assemble_ctx = ExecutionContext(
        workflow_id="wf-real-01",
        task_id="assemble-1",
        attempt=1,
        inputs={
            "deliverable_id": "course-real-01",
            "course_json_uri": author_result["course_json_uri"],
            "author_assets": author_result["assets"],
            "required_slots": [
                {
                    "kind": "video_slot",
                    "screen_id": "s-intro-video",
                    "slot_id": "intro-video",
                    "source_scene_ids": ("scene-intro-video",),
                    "title": "Video: intro-video",
                    "captions_required": False,
                }
            ],
            "video_insertions": [
                {
                    "slot_id": "intro-video",
                    "source_scene_ids": ("scene-intro-video",),
                    "video_uri": manim_result["video_uri"],
                    "video_media_type": "video/mp4",
                }
            ],
        },
    )
    assemble_result = await assembler.execute(assemble_ctx)

    assert assemble_result["video_count"] == 1
    assert assemble_result["unresolved_slot_count"] == 0
    assert assemble_result["screen_count"] >= 3


# ── Config integration ────────────────────────────────────────────────────────


def test_config_elearning_author_settings_requires_url(monkeypatch):
    """load_elearning_author_settings raises without credentials."""
    from learning_pipeline.config import load_elearning_author_settings
    from learning_pipeline.tools.errors import MissingRealModeConfigError

    monkeypatch.delenv("LITE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITE_LLM_API_KEY", raising=False)
    with pytest.raises(MissingRealModeConfigError, match="LITE_LLM_BASE_URL"):
        load_elearning_author_settings()


def test_config_elearning_author_settings_requires_key(monkeypatch):
    from learning_pipeline.config import load_elearning_author_settings
    from learning_pipeline.tools.errors import MissingRealModeConfigError

    monkeypatch.setenv("LITE_LLM_BASE_URL", "http://fake:4000")
    monkeypatch.delenv("LITE_LLM_API_KEY", raising=False)
    with pytest.raises(MissingRealModeConfigError, match="LITE_LLM_API_KEY"):
        load_elearning_author_settings()


def test_build_elearning_real_author_registry_with_settings(tmp_path, monkeypatch):
    from learning_pipeline.config import (
        ElearningAuthoringSettings,
        build_elearning_real_author_registry,
    )
    from learning_pipeline.tools.elearning_bundle.executor_real_author import (
        RealElearningCourseAuthorExecutor,
    )
    from learning_pipeline.tools.manim_video.executor_real import RealManimVideoExecutor

    monkeypatch.setenv("LITE_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("LITE_LLM_API_KEY", "fake-manim-key")
    monkeypatch.setenv("HEYGEN_API_KEY", "fake-heygen-key")

    settings = ElearningAuthoringSettings(
        litellm_base_url="http://fake-litellm:4000",
        litellm_api_key="fake-key",
        model_name="course-generator",
        input_cost_per_token=0.0,
        output_cost_per_token=0.0,
        artifact_store_root=tmp_path / "artifacts",
    )
    registry = build_elearning_real_author_registry(tmp_path / "artifacts", settings)
    author_executor = registry.get("elearning.course.author")
    assert isinstance(author_executor, RealElearningCourseAuthorExecutor)
    assert isinstance(registry.get("video.manim.render"), RealManimVideoExecutor)
    assert registry.get("elearning.bundle.assemble") is not None
