"""Planning chain integration test — Phase 10.

Tests the full chain:
  CourseBlueprint
    → PodcastModalityPlanner (fake client)
    → ModalityPlan
    → PodcastWorkflowPlanner (fake client)
    → ModalityProductionPlan
    → ProductionCompiler
    → BuildPlan
    → DAG validation
    → (optionally) fake execution
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.affordances.podcast import (
    PODCAST_SUPPORT_RULES,
    build_podcast_affordance_catalog,
    compute_producible_affordances,
)
from learning_pipeline.config import build_tool_catalog
from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    ModalityPlan,
    ModalityProductionPlan,
)
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    NarrativeRole,
    PodcastModalityDraft,
    PodcastSceneDraft,
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
)
from learning_pipeline.services.modality_planning import ModalityPlanningService
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.planners.modality.podcast.planner import PodcastModalityPlanner
from learning_pipeline.planners.workflow.podcast.planner import PodcastWorkflowPlanner
from learning_pipeline.services.workflow_planning import WorkflowPlanningService
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.repository import InMemoryRLORepository, RLODocument
from learning_pipeline.validation.build_plan import validate_build_plan

_RLO_ROOT = Path(__file__).parent.parent / "examples" / "reference" / "rlos"
_BP_PATH = Path(__file__).parent.parent / "examples" / "reference" / "podcast" / "course_blueprint.json"
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(
        (_RLO_ROOT / "rlo-adkar-01-name-and-sequence_v1.1.0.json").read_text(encoding="utf-8")
    )


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_modality_draft() -> PodcastModalityDraft:
    rlo_id = "rlo-adkar-01-name-and-sequence"
    return PodcastModalityDraft(
        draft_id="chain-modality-draft",
        title="ADKAR Episode",
        narrative="A podcast covering ADKAR fundamentals.",
        scenes=(
            PodcastSceneDraft(
                scene_id="scene-intro",
                source_content=(RLOContentRef(
                    rlo_id=rlo_id, rlo_version="1.1.0",
                    objective_ids=("lo-01",), concept_ids=("c-01",),
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
                    rlo_id=rlo_id, rlo_version="1.1.0",
                    objective_ids=(), concept_ids=(),
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
        narrative_summary="Workflow draft for ADKAR chain test.",
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


# ── Full chain: blueprint → modality plan → workflow plan → build plan ─────────


@pytest.mark.asyncio
async def test_full_planning_chain_produces_build_plan(tmp_path: Path) -> None:
    """Complete pipeline: blueprint → ModalityPlan → ModalityProductionPlan → BuildPlan."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    # Step 1: Modality planning (fake LLM)
    modality_draft = _make_modality_draft()
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="podcast_modality_v1")
    pp_modality = tmp_path / "podcast_modality_v1.md"
    pp_modality.write_text("# modality prompt", encoding="utf-8")

    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp_modality)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=PODCAST_SUPPORT_RULES,
        trace_root=tmp_path / "modality-traces",
    )
    modality_result = await modality_service.create_modality_plan(blueprint, Modality.PODCAST)
    modality_plan: ModalityPlan = modality_result.modality_plan

    assert isinstance(modality_plan, ModalityPlan)
    assert modality_plan.modality == Modality.PODCAST
    assert len(modality_plan.scenes) == 2

    # Step 2: Workflow planning (fake LLM, using the generated modality plan)
    workflow_draft = _make_workflow_draft(modality_plan)
    workflow_client = FakePlanningClient(draft=workflow_draft, prompt_version="podcast_v1")
    pp_workflow = tmp_path / "podcast_v1.md"
    pp_workflow.write_text("# workflow prompt", encoding="utf-8")

    compiler = ProductionCompiler(catalog)
    workflow_planner = PodcastWorkflowPlanner(client=workflow_client, catalog=catalog, prompt_path=pp_workflow)
    workflow_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    workflow_service = WorkflowPlanningService(
        resolver=workflow_resolver,
        planner=workflow_planner,
        compiler=compiler,
        trace_root=tmp_path / "workflow-traces",
    )
    workflow_result = await workflow_service.plan(blueprint, modality_plan)
    production_plan: ModalityProductionPlan = workflow_result.production_plan
    build_plan: BuildPlan = workflow_result.build_plan

    assert isinstance(production_plan, ModalityProductionPlan)
    assert isinstance(build_plan, BuildPlan)
    assert build_plan.modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_chain_build_plan_passes_dag_validation(tmp_path: Path) -> None:
    """BuildPlan from the full chain has a valid DAG structure."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    # Modality planning
    modality_draft = _make_modality_draft()
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="podcast_modality_v1")
    pp_modality = tmp_path / "pm.md"
    pp_modality.write_text("# prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp_modality)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver, planner=modality_planner, tool_catalog=catalog
    )
    modality_result = await modality_service.create_modality_plan(blueprint)
    modality_plan = modality_result.modality_plan

    # Workflow planning
    workflow_draft = _make_workflow_draft(modality_plan)
    workflow_client = FakePlanningClient(draft=workflow_draft, prompt_version="podcast_v1")
    pp_workflow = tmp_path / "pw.md"
    pp_workflow.write_text("# prompt", encoding="utf-8")
    compiler = ProductionCompiler(catalog)
    workflow_planner = PodcastWorkflowPlanner(client=workflow_client, catalog=catalog, prompt_path=pp_workflow)
    workflow_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    workflow_service = WorkflowPlanningService(
        resolver=workflow_resolver, planner=workflow_planner, compiler=compiler
    )
    workflow_result = await workflow_service.plan(blueprint, modality_plan)
    build_plan = workflow_result.build_plan

    validate_build_plan(build_plan, frozenset({"speech.synthesize", "audio.assemble"}))


@pytest.mark.asyncio
async def test_chain_coverage_is_complete(tmp_path: Path) -> None:
    """The modality plan covers all blueprint-selected content."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    modality_draft = _make_modality_draft()
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="podcast_modality_v1")
    pp = tmp_path / "pm.md"
    pp.write_text("# prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver, planner=modality_planner, tool_catalog=catalog
    )
    result = await modality_service.create_modality_plan(blueprint)
    assert result.coverage.uncovered_objective_ids == ()
    assert result.coverage.uncovered_concept_ids == ()
    assert result.coverage.uncovered_component_ids == ()
    assert result.coverage.uncovered_assessment_ids == ()


@pytest.mark.asyncio
async def test_modality_and_workflow_planners_are_independent(tmp_path: Path) -> None:
    """Modality planning service does not call the workflow planner."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    modality_draft = _make_modality_draft()
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="podcast_modality_v1")
    pp = tmp_path / "pm.md"
    pp.write_text("# prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver, planner=modality_planner, tool_catalog=catalog
    )

    result = await modality_service.create_modality_plan(blueprint)

    # The modality planning service should return only a ModalityPlan, not a BuildPlan
    assert not hasattr(result, "build_plan"), "ModalityPlanningResult must not contain a BuildPlan"
    assert not hasattr(result, "production_plan"), "ModalityPlanningResult must not contain a ModalityProductionPlan"
    assert isinstance(result.modality_plan, ModalityPlan)
