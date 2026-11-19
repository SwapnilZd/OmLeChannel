"""FormatSelectionService — explicit mode tests — Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    DeliveryConstraints,
    FormatSelectionMode,
    FormatSelectionRequest,
    FormatSelectionResult,
    SelectionBasis,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)
from learning_pipeline.format_selector.service import FormatSelectionError, FormatSelectionService

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_BP_PATH = Path(__file__).parents[2] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_service(caps: frozenset[str] = _PODCAST_CAPS, trace_root: Path | None = None) -> FormatSelectionService:
    registry = build_default_registry(available_capabilities=caps)
    return FormatSelectionService(registry=registry, profiles=MODALITY_PROFILES, trace_root=trace_root)


def _explicit_request(modality: Modality, *, allow_fallback: bool = False, **overrides) -> FormatSelectionRequest:
    blueprint = _load_blueprint()
    return FormatSelectionRequest(
        request_id="req-explicit",
        blueprint_id=blueprint.blueprint_id,
        mode=FormatSelectionMode.EXPLICIT,
        requested_modality=modality,
        allow_fallback=allow_fallback,
        **overrides,
    )


# ── Feasible explicit choice is selected regardless of score ──────────────────


@pytest.mark.asyncio
async def test_feasible_explicit_podcast_is_selected() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.PODCAST)
    result = await service.select_format(blueprint, request)
    assert isinstance(result, FormatSelectionResult)
    assert result.decision.selected_modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_explicit_selection_basis_is_explicit() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.PODCAST)
    result = await service.select_format(blueprint, request)
    assert result.decision.basis == SelectionBasis.EXPLICIT


@pytest.mark.asyncio
async def test_explicit_decision_has_no_fallback_from() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    result = await service.select_format(blueprint, _explicit_request(Modality.PODCAST))
    assert result.decision.fallback_from is None


@pytest.mark.asyncio
async def test_explicit_decision_contains_all_evaluations() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    result = await service.select_format(blueprint, _explicit_request(Modality.PODCAST))
    evaluated_modalities = {e.modality for e in result.decision.evaluations}
    assert evaluated_modalities == set(Modality)


# ── Infeasible explicit choice fails when fallback is disabled ─────────────────


@pytest.mark.asyncio
async def test_infeasible_explicit_choice_raises_without_fallback() -> None:
    blueprint = _load_blueprint()
    service = _make_service()  # only podcast available
    request = _explicit_request(Modality.VIDEO, allow_fallback=False)
    with pytest.raises(FormatSelectionError) as exc_info:
        await service.select_format(blueprint, request)
    err = exc_info.value
    assert len(err.blockers) > 0


@pytest.mark.asyncio
async def test_infeasible_error_lists_feasible_alternatives() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.VIDEO, allow_fallback=False)
    with pytest.raises(FormatSelectionError) as exc_info:
        await service.select_format(blueprint, request)
    assert Modality.PODCAST in exc_info.value.feasible_alternatives


# ── Fallback when explicit choice is infeasible ───────────────────────────────


@pytest.mark.asyncio
async def test_infeasible_explicit_selects_alternative_when_fallback_allowed() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.VIDEO, allow_fallback=True)
    result = await service.select_format(blueprint, request)
    assert result.decision.selected_modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_fallback_basis_is_explicit_fallback() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.VIDEO, allow_fallback=True)
    result = await service.select_format(blueprint, request)
    assert result.decision.basis == SelectionBasis.EXPLICIT_FALLBACK


@pytest.mark.asyncio
async def test_fallback_records_original_modality() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.VIDEO, allow_fallback=True)
    result = await service.select_format(blueprint, request)
    assert result.decision.fallback_from == Modality.VIDEO


@pytest.mark.asyncio
async def test_fallback_rationale_mentions_infeasible_modality() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = _explicit_request(Modality.VIDEO, allow_fallback=True)
    result = await service.select_format(blueprint, request)
    assert "video" in result.decision.rationale.lower()


# ── Blueprint / request mismatch is rejected ──────────────────────────────────


@pytest.mark.asyncio
async def test_blueprint_id_mismatch_raises() -> None:
    blueprint = _load_blueprint()
    service = _make_service()
    request = FormatSelectionRequest(
        request_id="req-01",
        blueprint_id="wrong-id",
        mode=FormatSelectionMode.EXPLICIT,
        requested_modality=Modality.PODCAST,
    )
    with pytest.raises(FormatSelectionError, match="mismatch"):
        await service.select_format(blueprint, request)


# ── No feasible alternatives when all fail ────────────────────────────────────


@pytest.mark.asyncio
async def test_fallback_with_no_feasible_alternatives_raises() -> None:
    blueprint = _load_blueprint()
    # No capabilities → all unavailable
    service = _make_service(caps=frozenset())
    request = _explicit_request(Modality.VIDEO, allow_fallback=True)
    with pytest.raises(FormatSelectionError):
        await service.select_format(blueprint, request)
