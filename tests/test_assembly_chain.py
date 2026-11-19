"""Full planning-chain integration test — Phase 12.

Tests the extended pipeline starting from RLO candidates:
  CourseAssemblyService (FakeCurriculumAssemblyAgent)
    → CourseBlueprint
    → FormatSelectionService                (Phase 11)
    → FormatSelectionResult (podcast)
    → PodcastModalityPlanner (FakePlanningClient)
    → ModalityPlan
    → PodcastWorkflowPlanner (FakePlanningClient)
    → ModalityProductionPlan
    → ProductionCompiler
    → BuildPlan
    → DAG validation

No live model or production provider is invoked.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.affordances.podcast import (
    PODCAST_SUPPORT_RULES,
    build_podcast_affordance_catalog,
)
from learning_pipeline.config import build_tool_catalog
from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    ModalityPlan,
    ModalityProductionPlan,
)
from learning_pipeline.contracts.common import Modality, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import AssemblyRLOCandidate, CourseAssemblyRequest
from learning_pipeline.contracts.format_selection import (
    FormatSelectionMode,
    FormatSelectionRequest,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    NarrativeRole,
    PodcastModalityDraft,
    PodcastProductionDraft,
    PodcastSceneDraft,
    PodcastSpeechSegmentDraft,
)
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.agent import FakeCurriculumAssemblyAgent
from learning_pipeline.planners.curriculum.service import CourseAssemblyService
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.registry import build_default_registry
from learning_pipeline.format_selector.service import FormatSelectionService
from learning_pipeline.services.modality_planning import ModalityPlanningService
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.planners.modality.podcast.planner import PodcastModalityPlanner
from learning_pipeline.planners.workflow.podcast.planner import PodcastWorkflowPlanner
from learning_pipeline.services.workflow_planning import WorkflowPlanningService
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.repository import InMemoryRLORepository
from learning_pipeline.validation.build_plan import validate_build_plan

_RLO_PATH = (
    Path(__file__).parent.parent
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_RLO_ID = "rlo-adkar-01-name-and-sequence"
_RLO_VERSION = "1.1.0"

_LEARNER = LearnerContext(
    role="Manager",
    deloitte_level=55,
    default_proficiency=TopicProficiency.BEGINNER,
    goals=("Understand ADKAR change management.",),
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _make_assembly_request(rlo: RLODocument) -> CourseAssemblyRequest:
    return CourseAssemblyRequest(
        request_id="chain-req-01",
        learner=_LEARNER,
        candidates=(AssemblyRLOCandidate(rlo_id=rlo.id, rlo_version=rlo.version),),
        course_goal="Understand ADKAR change management.",
    )


def _make_modality_draft() -> PodcastModalityDraft:
    return PodcastModalityDraft(
        draft_id="chain-modality-draft",
        title="ADKAR Episode",
        narrative="A podcast covering ADKAR fundamentals.",
        scenes=(
            PodcastSceneDraft(
                scene_id="scene-intro",
                source_content=(RLOContentRef(
                    rlo_id=_RLO_ID,
                    rlo_version=_RLO_VERSION,
                    objective_ids=("lo-01",),
                    concept_ids=("c-01",),
                    component_ids=("comp-hook-01", "comp-rule-01", "comp-example-01"),
                    assessment_item_ids=(),
                ),),
                learning_objective="Name the five ADKAR elements",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="hook_then_rule",
                content_direction="Introduce ADKAR.",
                target_duration_seconds=240,
            ),
            PodcastSceneDraft(
                scene_id="scene-apply",
                source_content=(RLOContentRef(
                    rlo_id=_RLO_ID,
                    rlo_version=_RLO_VERSION,
                    objective_ids=(),
                    concept_ids=(),
                    component_ids=("comp-example-02", "comp-nonexample-01", "comp-recall-01"),
                    assessment_item_ids=("q-01", "q-02"),
                ),),
                learning_objective="Apply ADKAR in context",
                narrative_role=NarrativeRole.ASSESSMENT,
                affordance_id="spoken_knowledge_check",
                teaching_pattern="example_nonexample",
                content_direction="Walk through examples and quiz.",
                target_duration_seconds=240,
            ),
        ),
    )


def _make_workflow_draft(modality_plan: ModalityPlan) -> PodcastProductionDraft:
    return PodcastProductionDraft(
        draft_id="chain-workflow-draft",
        title="ADKAR Workflow Draft",
        narrative_summary="Workflow draft for assembly chain test.",
        segments=tuple(
            PodcastSpeechSegmentDraft(
                segment_id=f"seg-{i + 1:02d}",
                source_scene_ids=(scene.id,),
                speaker="Host" if i % 2 == 0 else "Expert",
                text=f"Content for scene {scene.id}.",
                learning_purpose="Chain test segment",
            )
            for i, scene in enumerate(modality_plan.scenes)
        ),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assembly_chain_produces_blueprint(tmp_path: Path) -> None:
    """CourseAssemblyService produces a valid CourseBlueprint from RLO candidates."""
    rlo = _load_rlo()
    agent = FakeCurriculumAssemblyAgent()
    svc = CourseAssemblyService(agent, InMemoryRLORepository([rlo]))
    result = await svc.assemble_course(_make_assembly_request(rlo))
    assert isinstance(result.blueprint, CourseBlueprint)
    assert len(result.blueprint.ordered_rlo_refs) == 1
    assert result.blueprint.ordered_rlo_refs[0].rlo_id == rlo.id


@pytest.mark.asyncio
async def test_assembly_chain_format_selection_selects_podcast(tmp_path: Path) -> None:
    """Assembled blueprint feeds FormatSelectionService → selects podcast."""
    rlo = _load_rlo()
    svc = CourseAssemblyService(FakeCurriculumAssemblyAgent(), InMemoryRLORepository([rlo]))
    result = await svc.assemble_course(_make_assembly_request(rlo))
    blueprint = result.blueprint

    fs_svc = FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
    )
    fs_request = FormatSelectionRequest(
        request_id="chain-fs-01",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.AUTO,
    )
    fs_result = await fs_svc.select_format(blueprint, fs_request)
    assert fs_result.decision.selected_modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_assembly_chain_end_to_end(tmp_path: Path) -> None:
    """Full chain: RLO candidates → Assembly → FormatSelection → Modality → Workflow → BuildPlan."""
    rlo = _load_rlo()
    catalog = build_tool_catalog()

    # Step 1 — Curriculum Assembly
    assembly_svc = CourseAssemblyService(FakeCurriculumAssemblyAgent(), InMemoryRLORepository([rlo]))
    assembly_result = await assembly_svc.assemble_course(_make_assembly_request(rlo))
    blueprint = assembly_result.blueprint

    # Step 2 — Format Selection
    fs_svc = FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
    )
    fs_result = await fs_svc.select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="chain-fs-01",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.AUTO,
        ),
    )
    selected_modality = fs_result.decision.selected_modality
    assert selected_modality == Modality.PODCAST

    # Step 3 — Modality Planning
    pp_mod = tmp_path / "podcast_modality_v1.md"
    pp_mod.write_text("# modality prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(
        client=FakePlanningClient(draft=_make_modality_draft(), prompt_version="podcast_modality_v1"),
        prompt_path=pp_mod,
    )
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=PODCAST_SUPPORT_RULES,
        trace_root=tmp_path / "modality-traces",
    )
    modality_result = await modality_service.create_modality_plan(blueprint, selected_modality)
    modality_plan: ModalityPlan = modality_result.modality_plan
    assert isinstance(modality_plan, ModalityPlan)
    assert modality_plan.modality == Modality.PODCAST

    # Step 4 — Workflow Planning
    pp_wf = tmp_path / "podcast_v1.md"
    pp_wf.write_text("# workflow prompt", encoding="utf-8")
    compiler = ProductionCompiler(catalog)
    workflow_planner = PodcastWorkflowPlanner(
        client=FakePlanningClient(draft=_make_workflow_draft(modality_plan), prompt_version="podcast_v1"),
        catalog=catalog,
        prompt_path=pp_wf,
    )
    workflow_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    workflow_service = WorkflowPlanningService(
        resolver=workflow_resolver,
        planner=workflow_planner,
        compiler=compiler,
        trace_root=tmp_path / "workflow-traces",
    )
    workflow_result = await workflow_service.plan(blueprint, modality_plan)

    assert isinstance(workflow_result.production_plan, ModalityProductionPlan)
    assert isinstance(workflow_result.build_plan, BuildPlan)
    assert workflow_result.build_plan.modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_assembly_chain_dag_is_valid(tmp_path: Path) -> None:
    """BuildPlan produced by the full assembly chain passes DAG validation."""
    rlo = _load_rlo()
    catalog = build_tool_catalog()

    # Step 1 — Assembly
    assembly_svc = CourseAssemblyService(FakeCurriculumAssemblyAgent(), InMemoryRLORepository([rlo]))
    assembly_result = await assembly_svc.assemble_course(_make_assembly_request(rlo))
    blueprint = assembly_result.blueprint

    # Step 2 — Format Selection
    fs_result = await FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
    ).select_format(
        blueprint,
        FormatSelectionRequest(
            request_id="chain-fs-dag",
            blueprint_id=blueprint.blueprint_id,
            mode=FormatSelectionMode.AUTO,
        ),
    )
    selected_modality = fs_result.decision.selected_modality

    # Step 3 — Modality Planning
    pp_mod = tmp_path / "pm.md"
    pp_mod.write_text("# prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(
        client=FakePlanningClient(draft=_make_modality_draft(), prompt_version="podcast_modality_v1"),
        prompt_path=pp_mod,
    )
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=PODCAST_SUPPORT_RULES,
    )
    modality_result = await modality_service.create_modality_plan(blueprint, selected_modality)
    modality_plan = modality_result.modality_plan

    # Step 4 — Workflow Planning
    pp_wf = tmp_path / "pw.md"
    pp_wf.write_text("# prompt", encoding="utf-8")
    compiler = ProductionCompiler(catalog)
    workflow_planner = PodcastWorkflowPlanner(
        client=FakePlanningClient(draft=_make_workflow_draft(modality_plan), prompt_version="podcast_v1"),
        catalog=catalog,
        prompt_path=pp_wf,
    )
    workflow_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    workflow_service = WorkflowPlanningService(
        resolver=workflow_resolver,
        planner=workflow_planner,
        compiler=compiler,
    )
    workflow_result = await workflow_service.plan(blueprint, modality_plan)

    # Step 5 — DAG validation
    validate_build_plan(workflow_result.build_plan, _PODCAST_CAPS)
