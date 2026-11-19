"""Format selection chain integration test — Phase 11.

Tests the extended pipeline:
  CourseBlueprint
    → FormatSelectionService         (Phase 11)
    → FormatSelectionResult
    → PodcastModalityPlanner         (Phase 10)
    → ModalityPlan
    → PodcastWorkflowPlanner         (Phase 9)
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
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    FormatSelectionMode,
    FormatSelectionRequest,
    SelectionBasis,
)
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    NarrativeRole,
    PodcastModalityDraft,
    PodcastSceneDraft,
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
)
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
from learning_pipeline.repository import InMemoryRLORepository, RLODocument
from learning_pipeline.validation.build_plan import validate_build_plan

_RLO_ROOT = Path(__file__).parent.parent / "examples" / "reference" / "rlos"
_BP_PATH = Path(__file__).parent.parent / "examples" / "reference" / "podcast" / "course_blueprint.json"
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(
        (_RLO_ROOT / "rlo-adkar-01-name-and-sequence_v1.1.0.json").read_text(encoding="utf-8")
    )


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_format_selection_service() -> FormatSelectionService:
    return FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
    )


def _make_format_request(blueprint: CourseBlueprint) -> FormatSelectionRequest:
    return FormatSelectionRequest(
        request_id="req-chain-01",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.AUTO,
    )


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
        narrative_summary="Workflow draft for ADKAR format-selection chain test.",
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
async def test_format_selection_selects_podcast(tmp_path: Path) -> None:
    """FormatSelectionService selects podcast when only podcast is deployable."""
    blueprint = _load_blueprint()
    service = _make_format_selection_service()
    result = await service.select_format(blueprint, _make_format_request(blueprint))
    assert result.decision.selected_modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_format_selection_chain_produces_modality_plan(tmp_path: Path) -> None:
    """Format selection → Modality Planner produces a ModalityPlan for the selected modality."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    # Step 1 — Format Selection
    fs_service = _make_format_selection_service()
    fs_result = await fs_service.select_format(blueprint, _make_format_request(blueprint))
    selected_modality = fs_result.decision.selected_modality
    assert selected_modality == Modality.PODCAST

    # Step 2 — Modality Planning driven by the selected modality
    modality_draft = _make_modality_draft()
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="podcast_modality_v1")
    pp = tmp_path / "podcast_modality_v1.md"
    pp.write_text("# modality prompt", encoding="utf-8")

    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp)
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
    assert len(modality_plan.scenes) == 2


@pytest.mark.asyncio
async def test_format_selection_chain_end_to_end(tmp_path: Path) -> None:
    """Full chain: FormatSelection → ModalityPlan → WorkflowPlan → BuildPlan."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    # Step 1 — Format Selection
    fs_service = _make_format_selection_service()
    fs_result = await fs_service.select_format(blueprint, _make_format_request(blueprint))
    selected_modality = fs_result.decision.selected_modality

    # Step 2 — Modality Planning
    modality_draft = _make_modality_draft()
    modality_client = FakePlanningClient(draft=modality_draft, prompt_version="podcast_modality_v1")
    pp_mod = tmp_path / "podcast_modality_v1.md"
    pp_mod.write_text("# modality prompt", encoding="utf-8")

    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp_mod)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver,
        planner=modality_planner,
        tool_catalog=catalog,
        support_rules=PODCAST_SUPPORT_RULES,
        trace_root=tmp_path / "modality-traces",
    )
    modality_result = await modality_service.create_modality_plan(blueprint, selected_modality)
    modality_plan = modality_result.modality_plan

    # Step 3 — Workflow Planning (using the modality plan)
    workflow_draft = _make_workflow_draft(modality_plan)
    workflow_client = FakePlanningClient(draft=workflow_draft, prompt_version="podcast_v1")
    pp_wf = tmp_path / "podcast_v1.md"
    pp_wf.write_text("# workflow prompt", encoding="utf-8")

    compiler = ProductionCompiler(catalog)
    workflow_planner = PodcastWorkflowPlanner(client=workflow_client, catalog=catalog, prompt_path=pp_wf)
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
async def test_format_selection_chain_dag_is_valid(tmp_path: Path) -> None:
    """BuildPlan produced by the full chain (including Format Selection) passes DAG validation."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    # Step 1 — Format Selection
    fs_service = _make_format_selection_service()
    fs_result = await fs_service.select_format(blueprint, _make_format_request(blueprint))
    selected_modality = fs_result.decision.selected_modality

    # Step 2 — Modality Planning
    modality_client = FakePlanningClient(
        draft=_make_modality_draft(), prompt_version="podcast_modality_v1"
    )
    pp_mod = tmp_path / "pm.md"
    pp_mod.write_text("# prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp_mod)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver, planner=modality_planner, tool_catalog=catalog
    )
    modality_result = await modality_service.create_modality_plan(blueprint, selected_modality)
    modality_plan = modality_result.modality_plan

    # Step 3 — Workflow Planning
    workflow_client = FakePlanningClient(
        draft=_make_workflow_draft(modality_plan), prompt_version="podcast_v1"
    )
    pp_wf = tmp_path / "pw.md"
    pp_wf.write_text("# prompt", encoding="utf-8")
    compiler = ProductionCompiler(catalog)
    workflow_planner = PodcastWorkflowPlanner(client=workflow_client, catalog=catalog, prompt_path=pp_wf)
    workflow_resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    workflow_service = WorkflowPlanningService(
        resolver=workflow_resolver, planner=workflow_planner, compiler=compiler
    )
    workflow_result = await workflow_service.plan(blueprint, modality_plan)

    # Step 4 — DAG validation
    validate_build_plan(
        workflow_result.build_plan, frozenset({"speech.synthesize", "audio.assemble"})
    )


@pytest.mark.asyncio
async def test_format_selection_basis_is_sole_feasible(tmp_path: Path) -> None:
    """When only podcast is available, basis is SOLE_FEASIBLE (no scoring needed)."""
    blueprint = _load_blueprint()
    service = _make_format_selection_service()
    result = await service.select_format(blueprint, _make_format_request(blueprint))
    assert result.decision.basis == SelectionBasis.SOLE_FEASIBLE


@pytest.mark.asyncio
async def test_format_selection_result_modality_matches_modality_plan(tmp_path: Path) -> None:
    """The modality selected by format selection matches the modality in the modality plan."""
    rlo = _load_rlo()
    blueprint = _load_blueprint()
    catalog = build_tool_catalog()

    fs_service = _make_format_selection_service()
    fs_result = await fs_service.select_format(blueprint, _make_format_request(blueprint))
    selected_modality = fs_result.decision.selected_modality

    modality_client = FakePlanningClient(
        draft=_make_modality_draft(), prompt_version="podcast_modality_v1"
    )
    pp = tmp_path / "pm.md"
    pp.write_text("# prompt", encoding="utf-8")
    modality_planner = PodcastModalityPlanner(client=modality_client, prompt_path=pp)
    modality_resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    modality_service = ModalityPlanningService(
        resolver=modality_resolver, planner=modality_planner, tool_catalog=catalog
    )
    modality_result = await modality_service.create_modality_plan(blueprint, selected_modality)

    assert modality_result.modality_plan.modality == selected_modality
