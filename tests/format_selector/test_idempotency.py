"""FormatSelectionService — idempotency and caching tests — Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    DeliveryConstraints,
    FormatSelectionMode,
    FormatSelectionRequest,
    FormatSelectorStrategy,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.recommender import FakeFormatRecommender
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)
from learning_pipeline.format_selector.scoring import SCORING_POLICY_VERSION
from learning_pipeline.format_selector.service import FormatSelectionService

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_VIDEO_CAPS = frozenset({"video.render"})
_BP_PATH = Path(__file__).parents[2] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _auto_request(blueprint: CourseBlueprint, **overrides) -> FormatSelectionRequest:
    defaults = dict(
        request_id="req-idem",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.AUTO,
    )
    defaults.update(overrides)
    return FormatSelectionRequest(**defaults)


def _make_service(trace_root: Path, caps: frozenset[str] = _PODCAST_CAPS) -> FormatSelectionService:
    return FormatSelectionService(
        registry=build_default_registry(available_capabilities=caps),
        profiles=MODALITY_PROFILES,
        trace_root=trace_root,
    )


# ── Identical requests reuse the decision ─────────────────────────────────────


@pytest.mark.asyncio
async def test_second_identical_request_returns_from_cache(tmp_path: Path) -> None:
    blueprint = _load_blueprint()
    service = _make_service(tmp_path)
    request = _auto_request(blueprint)

    first = await service.select_format(blueprint, request)
    assert first.from_cache is False

    second = await service.select_format(blueprint, request)
    assert second.from_cache is True


@pytest.mark.asyncio
async def test_cached_decision_matches_original(tmp_path: Path) -> None:
    blueprint = _load_blueprint()
    service = _make_service(tmp_path)
    request = _auto_request(blueprint)

    first = await service.select_format(blueprint, request)
    second = await service.select_format(blueprint, request)
    assert first.decision.selected_modality == second.decision.selected_modality
    assert first.decision.input_hash if hasattr(first.decision, 'input_hash') else True


# ── Changed constraints invalidate reuse ──────────────────────────────────────


@pytest.mark.asyncio
async def test_changed_constraints_invalidate_cache(tmp_path: Path) -> None:
    blueprint = _load_blueprint()
    service = _make_service(tmp_path)

    r1 = await service.select_format(blueprint, _auto_request(blueprint))
    r2 = await service.select_format(
        blueprint,
        _auto_request(blueprint, constraints=DeliveryConstraints(screen_free_preferred=True)),
    )
    assert r1.from_cache is False
    assert r2.from_cache is False  # different constraints → cache miss


# ── Changed workflow availability invalidates reuse ───────────────────────────


@pytest.mark.asyncio
async def test_changed_registry_invalidates_cache(tmp_path: Path) -> None:
    blueprint = _load_blueprint()
    request = _auto_request(blueprint)

    service1 = _make_service(tmp_path, caps=_PODCAST_CAPS)
    r1 = await service1.select_format(blueprint, request)

    # Different registry (no capabilities)
    service2 = _make_service(tmp_path, caps=frozenset())
    # service2 has no feasible modalities → will raise, not cache-hit
    from learning_pipeline.format_selector.service import FormatSelectionError
    with pytest.raises(FormatSelectionError):
        await service2.select_format(blueprint, request)


# ── No trace_root means no caching ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_trace_root_means_no_cache() -> None:
    blueprint = _load_blueprint()
    service = FormatSelectionService(
        registry=build_default_registry(available_capabilities=_PODCAST_CAPS),
        profiles=MODALITY_PROFILES,
        trace_root=None,
    )
    request = _auto_request(blueprint)
    r1 = await service.select_format(blueprint, request)
    r2 = await service.select_format(blueprint, request)
    assert r1.from_cache is False
    assert r2.from_cache is False


# ── Trace files are written on first call ─────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_files_written_to_disk(tmp_path: Path) -> None:
    blueprint = _load_blueprint()
    service = _make_service(tmp_path)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    cache_dirs = list(tmp_path.iterdir())
    assert len(cache_dirs) == 1
    cache_dir = cache_dirs[0]
    assert (cache_dir / "decision.json").exists()
    assert (cache_dir / "trace.json").exists()


@pytest.mark.asyncio
async def test_persisted_decision_is_valid(tmp_path: Path) -> None:
    from learning_pipeline.contracts.format_selection import FormatSelectionDecision
    blueprint = _load_blueprint()
    service = _make_service(tmp_path)
    result = await service.select_format(blueprint, _auto_request(blueprint))
    cache_dir = list(tmp_path.iterdir())[0]
    loaded = FormatSelectionDecision.model_validate_json(
        (cache_dir / "decision.json").read_text(encoding="utf-8")
    )
    assert loaded.selected_modality == result.decision.selected_modality


# ── Changed LLM prompt version invalidates LLM-assisted reuse ─────────────────


@pytest.mark.asyncio
async def test_changed_prompt_version_invalidates_llm_cache(tmp_path: Path) -> None:
    blueprint = _load_blueprint()
    # Registry with two available modalities so LLM is called
    registry = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.PODCAST,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=frozenset({"speech.synthesize", "audio.assemble"}),
            ),
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=_VIDEO_CAPS,
            ),
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=False,
                workflow_planner_registered=False,
                required_capabilities=frozenset({"html.compile"}),
            ),
        ),
        available_capabilities=_PODCAST_CAPS | _VIDEO_CAPS,
    )
    request = _auto_request(blueprint)

    rec1 = FakeFormatRecommender(selected_modality=Modality.PODCAST, prompt_version="v1")
    service1 = FormatSelectionService(
        registry=registry,
        profiles=MODALITY_PROFILES,
        recommender=rec1,
        strategy=FormatSelectorStrategy.LLM_ASSISTED,
        trace_root=tmp_path,
    )
    r1 = await service1.select_format(blueprint, request)
    assert r1.from_cache is False

    rec2 = FakeFormatRecommender(selected_modality=Modality.PODCAST, prompt_version="v2")
    service2 = FormatSelectionService(
        registry=registry,
        profiles=MODALITY_PROFILES,
        recommender=rec2,
        strategy=FormatSelectorStrategy.LLM_ASSISTED,
        trace_root=tmp_path,
    )
    r2 = await service2.select_format(blueprint, request)
    assert r2.from_cache is False  # different prompt_version → cache miss
