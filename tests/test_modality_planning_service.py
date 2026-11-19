"""Tests for ModalityPlanningService — Phase 10."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.affordances.podcast import PODCAST_SUPPORT_RULES
from learning_pipeline.config import build_tool_catalog
from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    ModalityCoverageReport,
    ModalityPlanningResult,
    ModalityPlanningTrace,
    NarrativeRole,
    PodcastModalityDraft,
    PodcastSceneDraft,
)
from learning_pipeline.services.modality_planning import ModalityPlanningService
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.modality.context import ModalityContextResolver
from learning_pipeline.planners.modality.podcast.planner import PodcastModalityPlanner
from learning_pipeline.repository import InMemoryRLORepository, RLODocument

_RLO_ROOT = Path(__file__).parent.parent / "examples" / "reference" / "rlos"
_BP_PATH = Path(__file__).parent.parent / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_rlo() -> RLODocument:
    path = _RLO_ROOT / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
    return RLODocument.model_validate_json(path.read_text(encoding="utf-8"))


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_valid_draft() -> PodcastModalityDraft:
    rlo_id = "rlo-adkar-01-name-and-sequence"
    return PodcastModalityDraft(
        draft_id="svc-test-draft",
        title="ADKAR Episode",
        narrative="A podcast episode covering ADKAR.",
        scenes=(
            PodcastSceneDraft(
                scene_id="scene-intro",
                source_content=(RLOContentRef(
                    rlo_id=rlo_id,
                    rlo_version="1.1.0",
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
                    rlo_id=rlo_id,
                    rlo_version="1.1.0",
                    objective_ids=(),
                    concept_ids=(),
                    component_ids=("comp-example-02", "comp-nonexample-01", "comp-recall-01"),
                    assessment_item_ids=("q-01", "q-02"),
                ),),
                learning_objective="Apply ADKAR in practice",
                narrative_role=NarrativeRole.ASSESSMENT,
                affordance_id="spoken_knowledge_check",
                teaching_pattern="example_nonexample",
                content_direction="Apply and assess ADKAR knowledge.",
                target_duration_seconds=240,
            ),
        ),
    )


def _make_service(
    tmp_path: Path,
    *,
    with_trace_root: bool = True,
) -> tuple[ModalityPlanningService, FakePlanningClient]:
    rlo = _load_rlo()
    draft = _make_valid_draft()

    client = FakePlanningClient(draft=draft, prompt_version="podcast_modality_v1")
    catalog = build_tool_catalog()

    pp = tmp_path / "podcast_modality_v1.md"
    pp.write_text("# system prompt", encoding="utf-8")

    planner = PodcastModalityPlanner(client=client, prompt_path=pp)
    resolver = ModalityContextResolver(InMemoryRLORepository([rlo]))
    trace_root = tmp_path / "traces" if with_trace_root else None

    service = ModalityPlanningService(
        resolver=resolver,
        planner=planner,
        tool_catalog=catalog,
        support_rules=PODCAST_SUPPORT_RULES,
        trace_root=trace_root,
    )
    return service, client


# ── Basic planning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_returns_modality_planning_result(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert isinstance(result, ModalityPlanningResult)


@pytest.mark.asyncio
async def test_result_has_modality_plan(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert isinstance(result.modality_plan, ModalityPlan)


@pytest.mark.asyncio
async def test_result_has_coverage_report(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert isinstance(result.coverage, ModalityCoverageReport)


@pytest.mark.asyncio
async def test_result_has_trace(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert isinstance(result.trace, ModalityPlanningTrace)


@pytest.mark.asyncio
async def test_from_cache_false_first_run(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert result.from_cache is False


# ── Coverage content ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coverage_has_no_uncovered_objectives(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert result.coverage.uncovered_objective_ids == ()


@pytest.mark.asyncio
async def test_coverage_has_no_uncovered_assessments(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert result.coverage.uncovered_assessment_ids == ()


# ── Trace content ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_planner_type(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert result.trace.planner_type == "PodcastModalityPlanner"


@pytest.mark.asyncio
async def test_trace_modality_is_podcast(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert result.trace.modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_trace_context_hash_is_sha256(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert len(result.trace.context_hash) == 64


@pytest.mark.asyncio
async def test_trace_blueprint_hash_is_sha256(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert len(result.trace.blueprint_hash) == 64


# ── Idempotency ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_call_returns_cached(tmp_path: Path) -> None:
    service, client = _make_service(tmp_path)
    blueprint = _load_blueprint()

    first = await service.create_modality_plan(blueprint)
    assert first.from_cache is False
    assert client.call_count == 1

    second = await service.create_modality_plan(blueprint)
    assert second.from_cache is True
    assert client.call_count == 1  # no second LLM call


@pytest.mark.asyncio
async def test_cached_plan_matches_first(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    blueprint = _load_blueprint()
    first = await service.create_modality_plan(blueprint)
    second = await service.create_modality_plan(blueprint)
    assert first.modality_plan.model_dump_json() == second.modality_plan.model_dump_json()


@pytest.mark.asyncio
async def test_no_trace_root_skips_cache(tmp_path: Path) -> None:
    service, client = _make_service(tmp_path, with_trace_root=False)
    blueprint = _load_blueprint()
    first = await service.create_modality_plan(blueprint)
    second = await service.create_modality_plan(blueprint)
    assert first.from_cache is False
    assert second.from_cache is False
    assert client.call_count == 2


# ── Trace persistence ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_files_written_to_disk(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    ctx_hash = result.trace.context_hash
    # The cache is keyed by the full input hash (context + affordances + modality + ...)
    trace_dirs = list((tmp_path / "traces").iterdir())
    assert len(trace_dirs) == 1
    cache_dir = trace_dirs[0]
    assert (cache_dir / "modality_plan.json").exists()
    assert (cache_dir / "coverage_report.json").exists()
    assert (cache_dir / "trace.json").exists()


@pytest.mark.asyncio
async def test_persisted_plan_is_valid(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    trace_dirs = list((tmp_path / "traces").iterdir())
    cache_dir = trace_dirs[0]
    loaded = ModalityPlan.model_validate_json(
        (cache_dir / "modality_plan.json").read_text(encoding="utf-8")
    )
    assert loaded.plan_id == result.modality_plan.plan_id


# ── Custom request ID ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_request_id_in_trace(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(
        _load_blueprint(), planning_request_id="my-id-123"
    )
    assert result.trace.planning_request_id == "my-id-123"


@pytest.mark.asyncio
async def test_auto_uuid_generated_if_not_provided(tmp_path: Path) -> None:
    service, _ = _make_service(tmp_path)
    result = await service.create_modality_plan(_load_blueprint())
    assert len(result.trace.planning_request_id) == 36  # UUID4 length
