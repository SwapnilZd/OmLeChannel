"""Reference workflow tests for Phase 14D: ElearningWorkflowPlanner end-to-end.

Runs the full pipeline: planning → compile → execute with fake executors.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  1.  Authored-only plan → compile → execute produces a valid WorkflowResult.
  2.  Author task produces course JSON output.
  3.  Assembler task produces bundle_zip output.
  4.  Manim plan → compile → execute produces a valid WorkflowResult.
  5.  Avatar plan → compile → execute produces a valid WorkflowResult (custom registry).
  6.  BuildPlan compiled from authored-only plan has 2 tasks.
  7.  BuildPlan compiled from Manim plan has 3 tasks.
  8.  BuildPlan compiled from avatar plan has 3 tasks.
  9.  Assembler task depends on author task (DAG edge present).
  10. Manim task depends_on is empty (runs parallel to author).
"""
from __future__ import annotations

import hashlib

import pytest

from learning_pipeline.contracts import BuildPlan, Modality, ModalityPlan
from learning_pipeline.config import build_elearning_reference_registry, build_tool_catalog
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ManimMediaDirective,
)
from learning_pipeline.planners.workflow.elearning.builder import (
    ASSEMBLE_JOB_ID,
    AUTHOR_JOB_ID,
    ElearningProductionPlanBuilder,
)
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.runtime.persistence import FileRunStateStore
from learning_pipeline.runtime.runner import DAGRunner
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    VideoSlotRequirement,
)

# ── Constants for context ──────────────────────────────────────────────────────

_CTX_BYTES = b"{}"
_CTX_HASH = hashlib.sha256(_CTX_BYTES).hexdigest()
_CTX_URI = f"memory://planning-context/{_CTX_HASH[:16]}"

# ── Shared plan definition ─────────────────────────────────────────────────────

_ELEARNING_PLAN_JSON = """{
  "plan_id": "mp-ref-el-test",
  "modality": "elearning",
  "narrative": "Reference workflow test plan.",
  "scenes": [
    {
      "id": "scene-intro",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Understand the introduction.",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "elearning.static_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "introduce the topic clearly"
    },
    {
      "id": "scene-apply",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Apply the concept.",
      "teaching_pattern": "worked_example",
      "preferred_capability": "elearning.animated_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "show the concept with animation"
    }
  ]
}"""


def _plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_ELEARNING_PLAN_JSON)


def _authored(
    screen_id: str,
    scene_ids: tuple[str, ...],
    screen_type: str = "key_takeaways",
) -> AuthoredScreenRequirement:
    return AuthoredScreenRequirement(
        screen_id=screen_id,
        screen_type=screen_type,
        source_scene_ids=scene_ids,
        content_direction="Write clearly and concisely.",
    )


def _slot(
    screen_id: str,
    slot_id: str,
    scene_ids: tuple[str, ...],
    captions_required: bool = True,
) -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=screen_id,
        slot_id=slot_id,
        source_scene_ids=scene_ids,
        title=f"Video: {slot_id}",
        required=True,
        captions_required=captions_required,
    )


def _authored_only_draft() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="ref-authored-only",
        source_modality_plan_id="mp-ref-el-test",
        narrative="A reference authored-only course.",
        authored_screens=(
            _authored("screen-intro", ("scene-intro",), screen_type="title"),
            _authored("screen-apply", ("scene-apply",), screen_type="concept_flip_card"),
        ),
        video_slots=(),
        screen_order=("screen-intro", "screen-apply"),
        avatar_directives=(),
        manim_directives=(),
        course_authoring_direction="Write clear, professional content.",
    )


def _manim_draft() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="ref-manim",
        source_modality_plan_id="mp-ref-el-test",
        narrative="A reference Manim course.",
        authored_screens=(
            _authored("screen-intro", ("scene-intro",), screen_type="title"),
        ),
        video_slots=(
            _slot("screen-manim", "slot-manim", ("scene-apply",), captions_required=True),
        ),
        screen_order=("screen-intro", "screen-manim"),
        avatar_directives=(),
        manim_directives=(
            ManimMediaDirective(
                slot_id="slot-manim",
                narration_script="Watch this animation illustrating the concept.",
                animation_direction="Show a vertical stack of three steps.",
                voice_profile="default_narrator",
                target_duration_seconds=60,
            ),
        ),
        course_authoring_direction="Blend authored screens with animation.",
    )


def _avatar_draft() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="ref-avatar",
        source_modality_plan_id="mp-ref-el-test",
        narrative="A reference avatar course.",
        authored_screens=(
            _authored("screen-intro", ("scene-intro",), screen_type="title"),
        ),
        video_slots=(
            _slot("screen-avatar", "slot-avatar", ("scene-apply",), captions_required=True),
        ),
        screen_order=("screen-intro", "screen-avatar"),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-avatar",
                narration_script="Hello and welcome to this module.",
                avatar_profile="default_instructor",
                voice_profile="default_narrator",
                visual_direction="Dark background, instructor centered.",
                target_duration_seconds=60,
            ),
        ),
        manim_directives=(),
        course_authoring_direction="Use warm, encouraging tone.",
    )


_BUILDER = ElearningProductionPlanBuilder()


def _compile(draft: ElearningProductionDraft) -> BuildPlan:
    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    plan = _BUILDER.build(
        draft,
        modality_plan=_plan(),
        context_uri=_CTX_URI,
        context_hash=_CTX_HASH,
    )
    return compiler.compile(f"wf-ref-{draft.draft_id}", plan)


# ── 6: BuildPlan task counts ───────────────────────────────────────────────────

def test_authored_only_build_plan_has_two_tasks():
    bp = _compile(_authored_only_draft())
    assert len(bp.tasks) == 2


def test_manim_build_plan_has_three_tasks():
    bp = _compile(_manim_draft())
    assert len(bp.tasks) == 3


def test_avatar_build_plan_has_three_tasks():
    bp = _compile(_avatar_draft())
    assert len(bp.tasks) == 3


# ── 9: Assembler depends on author task ───────────────────────────────────────

def test_assembler_task_depends_on_author():
    bp = _compile(_authored_only_draft())
    by_id = {t.id: t for t in bp.tasks}
    assemble = by_id[ASSEMBLE_JOB_ID]
    assert AUTHOR_JOB_ID in assemble.depends_on


# ── 10: Manim task is independent (parallel to author) ────────────────────────

def test_manim_task_has_no_dependencies():
    from learning_pipeline.planners.workflow.elearning.builder import _manim_job_id
    bp = _compile(_manim_draft())
    by_id = {t.id: t for t in bp.tasks}
    manim_job_id = _manim_job_id("slot-manim")
    manim_task = by_id[manim_job_id]
    assert manim_task.depends_on == ()


# ── 1: Authored-only end-to-end ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authored_only_end_to_end(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    build_plan = _compile(_authored_only_draft())
    registry = build_elearning_reference_registry(artifact_root)
    store = FileRunStateStore(run_dir)
    result = await DAGRunner(registry, store).run(build_plan)

    assert result.workflow_id == build_plan.workflow_id
    assert set(result.task_results.keys()) == {AUTHOR_JOB_ID, ASSEMBLE_JOB_ID}
    for task_result in result.task_results.values():
        assert task_result.outputs, f"Task {task_result.task_id!r} produced no outputs"


# ── 2: Author task produces course_json output ────────────────────────────────

@pytest.mark.asyncio
async def test_author_task_produces_course_json(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    build_plan = _compile(_authored_only_draft())
    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(build_plan)

    author_outputs = result.task_results[AUTHOR_JOB_ID].outputs
    assert "course_json_uri" in author_outputs
    assert author_outputs["course_json_uri"]  # non-empty URI


# ── 3: Assembler produces bundle_zip ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_assembler_produces_bundle_zip(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    build_plan = _compile(_authored_only_draft())
    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(build_plan)

    assemble_outputs = result.task_results[ASSEMBLE_JOB_ID].outputs
    assert "bundle_zip" in assemble_outputs


# ── 4: Manim end-to-end ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manim_end_to_end(tmp_path):
    from learning_pipeline.planners.workflow.elearning.builder import _manim_job_id

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    build_plan = _compile(_manim_draft())
    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(build_plan)

    manim_job_id = _manim_job_id("slot-manim")
    expected_tasks = {AUTHOR_JOB_ID, manim_job_id, ASSEMBLE_JOB_ID}
    assert set(result.task_results.keys()) == expected_tasks
    for task_result in result.task_results.values():
        assert task_result.outputs, f"Task {task_result.task_id!r} produced no outputs"


# ── 5: Avatar end-to-end (custom registry with avatar store) ──────────────────

@pytest.mark.asyncio
async def test_avatar_end_to_end(tmp_path):
    from learning_pipeline.planners.workflow.elearning.builder import _avatar_job_id
    from learning_pipeline.runtime.artifact_store import FileArtifactStore

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    store = FileArtifactStore(artifact_root)
    registry = build_elearning_reference_registry(artifact_root, avatar_artifact_store=store)

    build_plan = _compile(_avatar_draft())
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(build_plan)

    avatar_job_id = _avatar_job_id("slot-avatar")
    expected_tasks = {AUTHOR_JOB_ID, avatar_job_id, ASSEMBLE_JOB_ID}
    assert set(result.task_results.keys()) == expected_tasks
    for task_result in result.task_results.values():
        assert task_result.outputs, f"Task {task_result.task_id!r} produced no outputs"


# ── Plan modality and narrative ───────────────────────────────────────────────

def test_compiled_plan_has_elearning_modality():
    bp = _compile(_authored_only_draft())
    assert bp.modality == "elearning"


def test_plan_narrative_in_production_plan():
    plan = _BUILDER.build(_authored_only_draft())
    assert "authored-only" in plan.narrative.lower() or plan.narrative


# ── ProductionCompiler integration ────────────────────────────────────────────

def test_production_compiler_maps_capabilities():
    bp = _compile(_authored_only_draft())
    task_types = {t.task_type for t in bp.tasks}
    assert "elearning.course.author" in task_types
    assert "elearning.bundle.assemble" in task_types


def test_manim_production_compiler_maps_manim_capability():
    bp = _compile(_manim_draft())
    task_types = {t.task_type for t in bp.tasks}
    assert "video.manim.render" in task_types


def test_avatar_production_compiler_maps_avatar_capability():
    bp = _compile(_avatar_draft())
    task_types = {t.task_type for t in bp.tasks}
    assert "video.avatar.render" in task_types
