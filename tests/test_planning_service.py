"""Tests for WorkflowPlanningService — Phase 9."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_pipeline.contracts import (
    BuildPlan,
    CourseBlueprint,
    ModalityPlan,
    ModalityProductionPlan,
)
from learning_pipeline.contracts.planning import (
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
    WorkflowPlanningResult,
)
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.workflow.podcast.planner import PodcastWorkflowPlanner
from learning_pipeline.services.workflow_planning import WorkflowPlanningService
from learning_pipeline.production import ProductionCompiler
from learning_pipeline.repository import InMemoryRLORepository, RLODocument

_RLO_ROOT = (
    Path(__file__).parent.parent / "examples" / "reference" / "rlos"
)
_BLUEPRINT_PATH = (
    Path(__file__).parent.parent
    / "examples" / "reference" / "podcast" / "course_blueprint.json"
)
_MODALITY_PLAN_PATH = (
    Path(__file__).parent.parent
    / "examples" / "reference" / "podcast" / "modality_plan.json"
)


def _load_rlo() -> RLODocument:
    path = _RLO_ROOT / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
    return RLODocument.model_validate_json(path.read_text(encoding="utf-8"))


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(
        _BLUEPRINT_PATH.read_text(encoding="utf-8")
    )


def _load_modality_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(
        _MODALITY_PLAN_PATH.read_text(encoding="utf-8")
    )


def _valid_draft(modality_plan: ModalityPlan) -> PodcastProductionDraft:
    return PodcastProductionDraft(
        draft_id="svc-test-draft",
        title="Service Test Episode",
        narrative_summary="Service test.",
        segments=tuple(
            PodcastSpeechSegmentDraft(
                segment_id=f"seg-{i + 1:02d}",
                source_scene_ids=(s.id,),
                speaker="Host" if i % 2 == 0 else "Expert",
                text="Hello world.",
                learning_purpose="test",
            )
            for i, s in enumerate(modality_plan.scenes)
        ),
    )


def _make_service(
    tmp_path: Path,
    *,
    with_trace_root: bool = True,
) -> tuple[WorkflowPlanningService, FakePlanningClient]:
    from learning_pipeline.config import build_tool_catalog

    rlo = _load_rlo()
    modality_plan = _load_modality_plan()
    draft = _valid_draft(modality_plan)

    client = FakePlanningClient(draft=draft)
    catalog = build_tool_catalog()
    compiler = ProductionCompiler(catalog)

    prompt_path = tmp_path / "podcast_v1.md"
    prompt_path.write_text("# system prompt", encoding="utf-8")

    planner = PodcastWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=prompt_path,
    )
    resolver = PlanningContextResolver(InMemoryRLORepository([rlo]))
    trace_root = tmp_path / "traces" if with_trace_root else None

    service = WorkflowPlanningService(
        resolver=resolver,
        planner=planner,
        compiler=compiler,
        catalog_hash="test-catalog-hash",
        trace_root=trace_root,
    )
    return service, client


# ── Basic planning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_returns_workflow_planning_result(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert isinstance(result, WorkflowPlanningResult)


@pytest.mark.asyncio
async def test_plan_result_has_production_plan(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert isinstance(result.production_plan, ModalityProductionPlan)


@pytest.mark.asyncio
async def test_plan_result_has_build_plan(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert isinstance(result.build_plan, BuildPlan)


@pytest.mark.asyncio
async def test_plan_result_not_from_cache_first_run(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert result.from_cache is False


@pytest.mark.asyncio
async def test_trace_has_correct_planner_type(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert result.trace.planner_type == "PodcastWorkflowPlanner"


@pytest.mark.asyncio
async def test_trace_has_catalog_hash(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert result.trace.capability_catalog_hash == "test-catalog-hash"


@pytest.mark.asyncio
async def test_trace_has_input_hash(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert len(result.trace.input_hash) == 64  # SHA-256 hex


# ── Idempotency ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_call_with_same_inputs_returns_cached(tmp_path: Path) -> None:
    service, client = _make_service(tmp_path)
    blueprint = _load_blueprint()
    modality_plan = _load_modality_plan()

    first = await service.plan(blueprint, modality_plan)
    assert first.from_cache is False
    assert client.call_count == 1

    second = await service.plan(blueprint, modality_plan)
    assert second.from_cache is True
    # LLM client must NOT be called a second time
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_cached_result_has_same_plan_as_first(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    blueprint = _load_blueprint()
    modality_plan = _load_modality_plan()

    first = await service.plan(blueprint, modality_plan)
    second = await service.plan(blueprint, modality_plan)

    assert (
        first.production_plan.model_dump_json()
        == second.production_plan.model_dump_json()
    )


@pytest.mark.asyncio
async def test_no_trace_root_skips_cache(tmp_path: Path) -> None:
    """Without trace_root, each call is a fresh plan (no caching)."""
    service, client = _make_service(tmp_path, with_trace_root=False)
    blueprint = _load_blueprint()
    modality_plan = _load_modality_plan()

    first = await service.plan(blueprint, modality_plan)
    second = await service.plan(blueprint, modality_plan)

    assert first.from_cache is False
    assert second.from_cache is False
    assert client.call_count == 2


# ── Trace persistence ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_files_written_to_disk(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    input_hash = result.trace.input_hash
    cache_dir = tmp_path / "traces" / input_hash
    assert (cache_dir / "production_plan.json").exists()
    assert (cache_dir / "build_plan.json").exists()
    assert (cache_dir / "trace.json").exists()


@pytest.mark.asyncio
async def test_persisted_production_plan_is_valid(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    input_hash = result.trace.input_hash
    cache_dir = tmp_path / "traces" / input_hash
    loaded = ModalityProductionPlan.model_validate_json(
        (cache_dir / "production_plan.json").read_text(encoding="utf-8")
    )
    assert loaded.plan_id == result.production_plan.plan_id


@pytest.mark.asyncio
async def test_persisted_build_plan_is_valid(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    input_hash = result.trace.input_hash
    cache_dir = tmp_path / "traces" / input_hash
    loaded = BuildPlan.model_validate_json(
        (cache_dir / "build_plan.json").read_text(encoding="utf-8")
    )
    assert loaded.workflow_id == result.build_plan.workflow_id


# ── Planning request ID ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_request_id_in_trace(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(
        _load_blueprint(),
        _load_modality_plan(),
        planning_request_id="my-request-id",
    )
    assert result.trace.planning_request_id == "my-request-id"


@pytest.mark.asyncio
async def test_auto_request_id_generated_if_not_provided(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.plan(_load_blueprint(), _load_modality_plan())
    assert result.trace.planning_request_id != ""
    assert len(result.trace.planning_request_id) == 36  # UUID format
