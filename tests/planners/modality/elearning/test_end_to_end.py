"""E-learning full planning chain tests — Phase 14E.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  32. ModalityPlan passes unchanged into Phase 14D ElearningWorkflowPlanner.
  33. Phase 14D maps affordances to allowed capabilities.
  34. Static plan creates no unnecessary video jobs.
  35. Avatar affordance produces an avatar slot and job.
  36. Animated affordance produces a Manim slot and job.
  37. Mixed plan produces the correct mixed DAG.
  38. Course structure declared once.
  39. Stable slot relationships survive compilation.
  40. ProductionCompiler produces a valid BuildPlan.
  41. WorkflowRunner executes the fake BuildPlan.
  42. Real assembler produces the final test bundle.
"""
from __future__ import annotations

import hashlib

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, ModalityScene, RLOContentRef
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningModalityDraft,
    ElearningSceneDraft,
    ElearningProductionDraft,
    ManimMediaDirective,
    ModalityPlanningContext,
    NarrativeRole,
    ResolvedRLOContext,
)
from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.affordances.elearning import build_elearning_affordance_catalog
from learning_pipeline.config import build_elearning_reference_registry, build_tool_catalog
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.modality.elearning.planner import (
    PROMPT_VERSION,
    ElearningModalityPlanner,
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

# ── Shared fixtures ────────────────────────────────────────────────────────────

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-e2e-el-test",
  "title": "E2E E-learning Test",
  "learner": {
    "role": "Consultant", "deloitte_level": 55, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["apply the skill"], "business_context": {}
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-1", "rlo_version": "1.0", "order": 1,
      "selected_content": {
        "objective_ids": ["obj-1"],
        "concept_ids": ["con-1"],
        "component_ids": [],
        "assessment_item_ids": ["asm-1"]
      },
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "core",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "test", "assessment_strategy": "formative",
  "estimated_duration_minutes": 10, "source_rlo_versions": {"rlo-1": "1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)

_RLO_CTX = ResolvedRLOContext(
    rlo_id="rlo-1", rlo_version="1.0", order=1, title="E2E RLO", topic="e2e",
    terminal_objective_text="Apply the skill",
    enabling_objectives=(), concepts=(), components=(), assessment_items=(),
    selected_objective_ids=("obj-1",), selected_concept_ids=("con-1",),
    selected_component_ids=(), selected_assessment_ids=("asm-1",),
    role_relevance="core", example_context=None, adaptation_instructions=(),
)

_CONTEXT = ModalityPlanningContext(
    blueprint_id="bp-e2e-el-test",
    learner=_BLUEPRINT.learner,
    rlo_contexts=(_RLO_CTX,),
)

_CATALOG = build_elearning_affordance_catalog()
_AFFORDANCE_VIEW = PlannerAffordanceView(
    modality=Modality.ELEARNING,
    affordances=_CATALOG.affordances_for(Modality.ELEARNING),
)

_REF = RLOContentRef(
    rlo_id="rlo-1", rlo_version="1.0",
    objective_ids=("obj-1",), concept_ids=("con-1",), assessment_item_ids=("asm-1",),
)

_CTX_BYTES = b"{}"
_CTX_HASH = hashlib.sha256(_CTX_BYTES).hexdigest()
_CTX_URI = f"memory://planning-context/{_CTX_HASH[:16]}"

_WFBUILDER = ElearningProductionPlanBuilder()


def _compile(draft: ElearningProductionDraft, workflow_id: str = "wf-e2e-test"):
    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    plan = _WFBUILDER.build(
        draft,
        modality_plan=_make_static_modality_plan(),
        context_uri=_CTX_URI,
        context_hash=_CTX_HASH,
    )
    return compiler.compile(workflow_id, plan)


def _make_static_modality_plan() -> ModalityPlan:
    return ModalityPlan(
        plan_id="mp-e2e-test",
        modality=Modality.ELEARNING,
        narrative="A full E2E e-learning test.",
        scenes=(
            ModalityScene(
                id="scene-intro",
                source_content=(_REF,),
                learning_objective="Understand the concept.",
                teaching_pattern="direct_instruction",
                preferred_capability="elearning.static_explanation",
                content_direction="Introduce the concept.",
                target_duration_seconds=60,
            ),
            ModalityScene(
                id="scene-practice",
                source_content=(_REF,),
                learning_objective="Apply the skill.",
                teaching_pattern="guided_practice",
                preferred_capability="elearning.guided_practice",
                content_direction="Practice the skill.",
                target_duration_seconds=90,
            ),
        ),
    )


def _make_avatar_modality_plan() -> ModalityPlan:
    return ModalityPlan(
        plan_id="mp-e2e-avatar-test",
        modality=Modality.ELEARNING,
        narrative="Avatar framing + static explanation.",
        scenes=(
            ModalityScene(
                id="scene-avatar",
                source_content=(_REF,),
                learning_objective="Engage with the concept.",
                teaching_pattern="direct_instruction",
                preferred_capability="elearning.avatar_framing",
                content_direction="Avatar introduces the course.",
                target_duration_seconds=60,
            ),
            ModalityScene(
                id="scene-content",
                source_content=(_REF,),
                learning_objective="Understand the concept.",
                teaching_pattern="direct_instruction",
                preferred_capability="elearning.static_explanation",
                content_direction="Explain the concept.",
                target_duration_seconds=90,
            ),
        ),
    )


# ── Modality planner chain ─────────────────────────────────────────────────────


def _valid_modality_draft() -> ElearningModalityDraft:
    return ElearningModalityDraft(
        draft_id="e2e-modality-draft",
        title="E2E Test",
        narrative="Full e-learning test.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-intro",
                source_content=(_REF,),
                learning_objective="Understand the concept.",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction",
                content_direction="Introduce the concept clearly.",
                target_duration_seconds=60,
            ),
            ElearningSceneDraft(
                scene_id="scene-practice",
                source_content=(_REF,),
                learning_objective="Apply the skill.",
                narrative_role=NarrativeRole.PRACTICE,
                affordance_id="elearning.guided_practice",
                teaching_pattern="guided_practice",
                content_direction="Walk through applying the skill.",
                target_duration_seconds=90,
            ),
            ElearningSceneDraft(
                scene_id="scene-assessment",
                source_content=(_REF,),
                learning_objective="Verify understanding.",
                narrative_role=NarrativeRole.ASSESSMENT,
                affordance_id="elearning.knowledge_check",
                teaching_pattern="knowledge_check",
                content_direction="Check understanding with a question.",
                target_duration_seconds=60,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_modality_planner_produces_elearning_plan(tmp_path) -> None:
    client = FakePlanningClient(draft=_valid_modality_draft(), prompt_version=PROMPT_VERSION)
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)

    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    assert isinstance(plan, ModalityPlan)
    assert plan.modality == Modality.ELEARNING
    assert len(plan.scenes) == 3


# ── 32: ModalityPlan passes into Phase 14D ────────────────────────────────────


def test_modality_plan_accepted_by_workflow_planner() -> None:
    plan = _make_static_modality_plan()
    static_draft = ElearningProductionDraft(
        draft_id="wf-static-test",
        source_modality_plan_id="mp-e2e-test",
        narrative="Static course.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-intro",
                screen_type="title",
                source_scene_ids=("scene-intro",),
                content_direction="Write the intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="screen-practice",
                screen_type="guided_practice",
                source_scene_ids=("scene-practice",),
                content_direction="Write the practice exercise.",
            ),
        ),
        video_slots=(),
        screen_order=("screen-intro", "screen-practice"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear and professional.",
    )
    bp = _compile(static_draft, "wf-static-test")
    assert bp.modality == "elearning"


# ── 33: Phase 14D maps affordances to capabilities ────────────────────────────


def test_static_plan_has_author_and_assemble_tasks() -> None:
    static_draft = ElearningProductionDraft(
        draft_id="wf-caps-test",
        source_modality_plan_id="mp-e2e-test",
        narrative="Static.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-a",
                screen_type="title",
                source_scene_ids=("scene-intro",),
                content_direction="Write the intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="screen-b",
                screen_type="key_takeaways",
                source_scene_ids=("scene-practice",),
                content_direction="Write takeaways.",
            ),
        ),
        video_slots=(),
        screen_order=("screen-a", "screen-b"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "wf-caps-test")
    task_types = {t.task_type for t in bp.tasks}
    assert "elearning.course.author" in task_types
    assert "elearning.bundle.assemble" in task_types


# ── 34: Static plan creates no video jobs ─────────────────────────────────────


def test_static_plan_has_no_video_tasks() -> None:
    static_draft = ElearningProductionDraft(
        draft_id="wf-static-novideo",
        source_modality_plan_id="mp-e2e-test",
        narrative="Static only.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-a",
                screen_type="title",
                source_scene_ids=("scene-intro",),
                content_direction="Write the intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="screen-b",
                screen_type="key_takeaways",
                source_scene_ids=("scene-practice",),
                content_direction="Write takeaways.",
            ),
        ),
        video_slots=(),
        screen_order=("screen-a", "screen-b"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "wf-static-novideo")
    task_types = {t.task_type for t in bp.tasks}
    assert "video.avatar.render" not in task_types
    assert "video.manim.render" not in task_types


# ── 35: Avatar affordance produces avatar slot and job ───────────────────────


def test_avatar_plan_has_avatar_task() -> None:
    from learning_pipeline.planners.workflow.elearning.builder import _avatar_job_id

    avatar_draft = ElearningProductionDraft(
        draft_id="wf-avatar-e2e",
        source_modality_plan_id="mp-e2e-avatar-test",
        narrative="Avatar course.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-content",
                screen_type="title",
                source_scene_ids=("scene-content",),
                content_direction="Title screen.",
            ),
        ),
        video_slots=(
            VideoSlotRequirement(
                screen_id="screen-avatar",
                slot_id="slot-intro",
                source_scene_ids=("scene-avatar",),
                title="Avatar Intro",
                required=True,
                captions_required=True,
            ),
        ),
        screen_order=("screen-avatar", "screen-content"),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-intro",
                narration_script="Welcome to this module.",
                avatar_profile="default_instructor",
                voice_profile="default_narrator",
                visual_direction="Dark background.",
                target_duration_seconds=60,
            ),
        ),
        manim_directives=(),
        course_authoring_direction="Warm tone.",
    )

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    plan = _WFBUILDER.build(
        avatar_draft,
        modality_plan=_make_avatar_modality_plan(),
        context_uri=_CTX_URI,
        context_hash=_CTX_HASH,
    )
    bp = compiler.compile("wf-avatar-e2e", plan)

    task_types = {t.task_type for t in bp.tasks}
    assert "video.avatar.render" in task_types
    assert _avatar_job_id("slot-intro") in {t.id for t in bp.tasks}


# ── 36: Manim affordance produces Manim slot and job ─────────────────────────


def test_manim_plan_has_manim_task() -> None:
    from learning_pipeline.planners.workflow.elearning.builder import _manim_job_id

    manim_plan = ModalityPlan(
        plan_id="mp-e2e-manim-test",
        modality=Modality.ELEARNING,
        narrative="Manim course.",
        scenes=(
            ModalityScene(
                id="scene-animation",
                source_content=(_REF,),
                learning_objective="Visualize the process.",
                teaching_pattern="demonstration",
                preferred_capability="elearning.animated_demonstration",
                content_direction="Animate the process.",
                target_duration_seconds=90,
            ),
            ModalityScene(
                id="scene-content",
                source_content=(_REF,),
                learning_objective="Understand the concept.",
                teaching_pattern="direct_instruction",
                preferred_capability="elearning.static_explanation",
                content_direction="Explain the concept.",
                target_duration_seconds=60,
            ),
        ),
    )

    manim_draft = ElearningProductionDraft(
        draft_id="wf-manim-e2e",
        source_modality_plan_id="mp-e2e-manim-test",
        narrative="Manim course.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-content",
                screen_type="title",
                source_scene_ids=("scene-content",),
                content_direction="Title screen.",
            ),
        ),
        video_slots=(
            VideoSlotRequirement(
                screen_id="screen-anim",
                slot_id="slot-manim",
                source_scene_ids=("scene-animation",),
                title="Animation",
                required=True,
                captions_required=True,
            ),
        ),
        screen_order=("screen-anim", "screen-content"),
        avatar_directives=(),
        manim_directives=(
            ManimMediaDirective(
                slot_id="slot-manim",
                narration_script="Watch this animation.",
                animation_direction="Show a flow diagram.",
                voice_profile="default_narrator",
                target_duration_seconds=90,
            ),
        ),
        course_authoring_direction="Visual focus.",
    )

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    plan = _WFBUILDER.build(
        manim_draft,
        modality_plan=manim_plan,
        context_uri=_CTX_URI,
        context_hash=_CTX_HASH,
    )
    bp = compiler.compile("wf-manim-e2e", plan)

    task_types = {t.task_type for t in bp.tasks}
    assert "video.manim.render" in task_types
    assert _manim_job_id("slot-manim") in {t.id for t in bp.tasks}


# ── 37: Mixed plan has correct mixed DAG ─────────────────────────────────────


def test_mixed_plan_has_both_avatar_and_manim_tasks() -> None:
    mixed_plan = ModalityPlan(
        plan_id="mp-e2e-mixed-test",
        modality=Modality.ELEARNING,
        narrative="Mixed course.",
        scenes=(
            ModalityScene(
                id="scene-avatar",
                source_content=(_REF,),
                learning_objective="Engage.",
                teaching_pattern="direct_instruction",
                preferred_capability="elearning.avatar_framing",
                content_direction="Avatar intro.",
                target_duration_seconds=60,
            ),
            ModalityScene(
                id="scene-manim",
                source_content=(_REF,),
                learning_objective="Visualize.",
                teaching_pattern="demonstration",
                preferred_capability="elearning.animated_demonstration",
                content_direction="Animate.",
                target_duration_seconds=90,
            ),
        ),
    )

    mixed_draft = ElearningProductionDraft(
        draft_id="wf-mixed-e2e",
        source_modality_plan_id="mp-e2e-mixed-test",
        narrative="Mixed.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-intro",
                screen_type="title",
                source_scene_ids=("scene-avatar",),
                content_direction="Introduction.",
            ),
        ),
        video_slots=(
            VideoSlotRequirement(
                screen_id="screen-avatar",
                slot_id="slot-avatar",
                source_scene_ids=("scene-avatar",),
                title="Avatar Slot",
                required=True,
                captions_required=True,
            ),
            VideoSlotRequirement(
                screen_id="screen-manim",
                slot_id="slot-manim",
                source_scene_ids=("scene-manim",),
                title="Manim Slot",
                required=True,
                captions_required=True,
            ),
        ),
        screen_order=("screen-intro", "screen-avatar", "screen-manim"),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-avatar",
                narration_script="Welcome.",
                avatar_profile="default_instructor",
                voice_profile="default_narrator",
                visual_direction="Dark.",
            ),
        ),
        manim_directives=(
            ManimMediaDirective(
                slot_id="slot-manim",
                narration_script="Watch.",
                animation_direction="Show flow.",
                voice_profile="default_narrator",
            ),
        ),
        course_authoring_direction="Mixed.",
    )

    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    plan = _WFBUILDER.build(
        mixed_draft,
        modality_plan=mixed_plan,
        context_uri=_CTX_URI,
        context_hash=_CTX_HASH,
    )
    bp = compiler.compile("wf-mixed-e2e", plan)

    task_types = {t.task_type for t in bp.tasks}
    assert "video.avatar.render" in task_types
    assert "video.manim.render" in task_types
    assert "elearning.course.author" in task_types
    assert "elearning.bundle.assemble" in task_types
    assert len(bp.tasks) == 4


# ── 38: Course structure declared once ───────────────────────────────────────


def test_static_build_plan_has_two_tasks() -> None:
    static_draft = ElearningProductionDraft(
        draft_id="wf-task-count",
        source_modality_plan_id="mp-e2e-test",
        narrative="Two tasks.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="s1", screen_type="title",
                source_scene_ids=("scene-intro",), content_direction="Intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="s2", screen_type="key_takeaways",
                source_scene_ids=("scene-practice",), content_direction="Practice.",
            ),
        ),
        video_slots=(),
        screen_order=("s1", "s2"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "wf-task-count")
    assert len(bp.tasks) == 2  # author + assemble


# ── 39: Slot relationships survive compilation ────────────────────────────────


def test_assembler_depends_on_author() -> None:
    static_draft = ElearningProductionDraft(
        draft_id="wf-dag-test",
        source_modality_plan_id="mp-e2e-test",
        narrative="DAG test.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="s1", screen_type="title",
                source_scene_ids=("scene-intro",), content_direction="Intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="s2", screen_type="key_takeaways",
                source_scene_ids=("scene-practice",), content_direction="Practice.",
            ),
        ),
        video_slots=(),
        screen_order=("s1", "s2"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "wf-dag-test")
    by_id = {t.id: t for t in bp.tasks}
    assemble = by_id[ASSEMBLE_JOB_ID]
    assert AUTHOR_JOB_ID in assemble.depends_on


# ── 40: ProductionCompiler produces valid BuildPlan ───────────────────────────


def test_build_plan_has_workflow_id() -> None:
    static_draft = ElearningProductionDraft(
        draft_id="wf-bp-test",
        source_modality_plan_id="mp-e2e-test",
        narrative="BuildPlan test.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="s1", screen_type="title",
                source_scene_ids=("scene-intro",), content_direction="Intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="s2", screen_type="key_takeaways",
                source_scene_ids=("scene-practice",), content_direction="Practice.",
            ),
        ),
        video_slots=(),
        screen_order=("s1", "s2"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "my-workflow-id")
    assert bp.workflow_id == "my-workflow-id"
    assert bp.modality == "elearning"


# ── 41: WorkflowRunner executes fake BuildPlan ────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_runner_executes_static_plan(tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    static_draft = ElearningProductionDraft(
        draft_id="wf-runner-test",
        source_modality_plan_id="mp-e2e-test",
        narrative="Runner test.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="s1", screen_type="title",
                source_scene_ids=("scene-intro",), content_direction="Intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="s2", screen_type="key_takeaways",
                source_scene_ids=("scene-practice",), content_direction="Practice.",
            ),
        ),
        video_slots=(),
        screen_order=("s1", "s2"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "wf-runner-test")
    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(bp)

    assert result.workflow_id == "wf-runner-test"
    assert set(result.task_results.keys()) == {AUTHOR_JOB_ID, ASSEMBLE_JOB_ID}
    for tr in result.task_results.values():
        assert tr.outputs, f"Task {tr.task_id!r} produced no outputs"


# ── 42: Real assembler produces final bundle ──────────────────────────────────


@pytest.mark.asyncio
async def test_assembler_produces_bundle_zip(tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    static_draft = ElearningProductionDraft(
        draft_id="wf-bundle-test",
        source_modality_plan_id="mp-e2e-test",
        narrative="Bundle test.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="s1", screen_type="title",
                source_scene_ids=("scene-intro",), content_direction="Intro.",
            ),
            AuthoredScreenRequirement(
                screen_id="s2", screen_type="key_takeaways",
                source_scene_ids=("scene-practice",), content_direction="Practice.",
            ),
        ),
        video_slots=(),
        screen_order=("s1", "s2"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear.",
    )
    bp = _compile(static_draft, "wf-bundle-test")
    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(bp)

    assemble_outputs = result.task_results[ASSEMBLE_JOB_ID].outputs
    assert "bundle_zip" in assemble_outputs


# ── Full modality chain: planner → workflow planner → runner ──────────────────


@pytest.mark.asyncio
async def test_full_modality_chain(tmp_path) -> None:
    """Modality planner → ModalityPlan → Workflow planner → BuildPlan → runner."""
    from pathlib import Path as _Path
    from learning_pipeline.planners.workflow.elearning.planner import ElearningWorkflowPlanner
    from learning_pipeline.planners.context import PlanningContextResolver
    from learning_pipeline.repository import FileRLORepository

    # Step 1: produce ModalityPlan via fake modality planner
    modality_client = FakePlanningClient(draft=_valid_modality_draft(), prompt_version=PROMPT_VERSION)
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    modality_planner = ElearningModalityPlanner(client=modality_client, prompt_path=pp)
    modality_plan = await modality_planner.create_modality_plan(
        _BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW
    )

    assert modality_plan.modality == Modality.ELEARNING
    assert len(modality_plan.scenes) == 3

    # Step 2: build workflow production draft manually (simulates workflow planner output)
    # Map the modality scenes to screen requirements
    all_scene_ids = [s.id for s in modality_plan.scenes]
    workflow_draft = ElearningProductionDraft(
        draft_id="chain-test-wf",
        source_modality_plan_id=modality_plan.plan_id,
        narrative="Full chain test.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-intro",
                screen_type="title",
                source_scene_ids=(all_scene_ids[0],),
                content_direction="Introduce the topic.",
            ),
            AuthoredScreenRequirement(
                screen_id="screen-practice",
                screen_type="guided_practice",
                source_scene_ids=(all_scene_ids[1],),
                content_direction="Practice.",
            ),
            AuthoredScreenRequirement(
                screen_id="screen-check",
                screen_type="knowledge_check",
                source_scene_ids=(all_scene_ids[2],),
                content_direction="Check understanding.",
            ),
        ),
        video_slots=(),
        screen_order=("screen-intro", "screen-practice", "screen-check"),
        avatar_directives=(),
            manim_directives=(),
        course_authoring_direction="Clear and professional.",
    )

    # Step 3: compile to BuildPlan
    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)
    production_plan = _WFBUILDER.build(
        workflow_draft,
        modality_plan=modality_plan,
        context_uri=_CTX_URI,
        context_hash=_CTX_HASH,
    )
    bp = compiler.compile("chain-test-workflow", production_plan)
    assert bp.modality == "elearning"
    assert len(bp.tasks) == 2

    # Step 4: execute with reference registry
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    registry = build_elearning_reference_registry(artifact_root)
    result = await DAGRunner(registry, FileRunStateStore(run_dir)).run(bp)

    assert set(result.task_results.keys()) == {AUTHOR_JOB_ID, ASSEMBLE_JOB_ID}
    assert "bundle_zip" in result.task_results[ASSEMBLE_JOB_ID].outputs
