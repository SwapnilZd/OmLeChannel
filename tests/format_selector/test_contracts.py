"""Format selection contract validation tests — Phase 11."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    DeliveryConstraints,
    FormatSelectionMode,
    FormatSelectionRequest,
)


def _make_request(**overrides) -> FormatSelectionRequest:
    defaults = dict(
        request_id="req-01",
        blueprint_id="bp-01",
        mode=FormatSelectionMode.EXPLICIT,
        requested_modality=Modality.PODCAST,
    )
    defaults.update(overrides)
    return FormatSelectionRequest(**defaults)


# ── Valid requests ─────────────────────────────────────────────────────────────


def test_valid_explicit_request() -> None:
    req = _make_request()
    assert req.mode == FormatSelectionMode.EXPLICIT
    assert req.requested_modality == Modality.PODCAST


def test_valid_auto_request() -> None:
    req = FormatSelectionRequest(
        request_id="req-auto",
        blueprint_id="bp-01",
        mode=FormatSelectionMode.AUTO,
    )
    assert req.mode == FormatSelectionMode.AUTO
    assert req.requested_modality is None


def test_explicit_request_defaults() -> None:
    req = _make_request()
    assert req.allow_fallback is False
    assert req.preferred_modalities == ()


# ── Explicit mode without modality fails ──────────────────────────────────────


def test_explicit_mode_without_modality_fails() -> None:
    with pytest.raises(ValidationError, match="explicit mode requires requested_modality"):
        FormatSelectionRequest(
            request_id="req",
            blueprint_id="bp",
            mode=FormatSelectionMode.EXPLICIT,
        )


# ── Auto mode with modality fails ─────────────────────────────────────────────


def test_auto_mode_with_requested_modality_fails() -> None:
    with pytest.raises(ValidationError, match="auto mode must not specify requested_modality"):
        FormatSelectionRequest(
            request_id="req",
            blueprint_id="bp",
            mode=FormatSelectionMode.AUTO,
            requested_modality=Modality.PODCAST,
        )


# ── Duplicate preferences fail ────────────────────────────────────────────────


def test_duplicate_preferred_modalities_fail() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _make_request(
            mode=FormatSelectionMode.AUTO,
            requested_modality=None,
            preferred_modalities=(Modality.PODCAST, Modality.PODCAST),
        )


# ── Preferred and excluded conflicts fail ─────────────────────────────────────


def test_preferred_and_excluded_overlap_fails() -> None:
    with pytest.raises(ValidationError, match="both preferred and excluded"):
        _make_request(
            mode=FormatSelectionMode.AUTO,
            requested_modality=None,
            preferred_modalities=(Modality.PODCAST,),
            constraints=DeliveryConstraints(excluded_modalities=(Modality.PODCAST,)),
        )


# ── Explicit requested modality cannot be excluded ────────────────────────────


def test_explicit_requested_modality_cannot_be_excluded() -> None:
    with pytest.raises(ValidationError, match="cannot also be excluded"):
        _make_request(
            constraints=DeliveryConstraints(excluded_modalities=(Modality.PODCAST,)),
        )


# ── Duplicate exclusions fail ─────────────────────────────────────────────────


def test_duplicate_excluded_modalities_fail() -> None:
    with pytest.raises(ValidationError, match="unique"):
        DeliveryConstraints(excluded_modalities=(Modality.VIDEO, Modality.VIDEO))


# ── Invalid numeric constraints fail ─────────────────────────────────────────


def test_zero_maximum_delivery_minutes_fails() -> None:
    with pytest.raises(ValidationError, match="positive"):
        DeliveryConstraints(maximum_delivery_minutes=0)


def test_negative_production_cost_fails() -> None:
    with pytest.raises(ValidationError, match="positive"):
        DeliveryConstraints(maximum_production_cost_usd=-1.0)


def test_zero_artifact_size_fails() -> None:
    with pytest.raises(ValidationError, match="positive"):
        DeliveryConstraints(maximum_artifact_size_mb=0.0)


def test_positive_constraints_accepted() -> None:
    c = DeliveryConstraints(
        maximum_delivery_minutes=30,
        maximum_production_cost_usd=10.0,
        maximum_artifact_size_mb=100.0,
    )
    assert c.maximum_delivery_minutes == 30


# ── Request ID non-empty ──────────────────────────────────────────────────────


def test_empty_request_id_fails() -> None:
    with pytest.raises(ValidationError):
        _make_request(request_id="")


def test_empty_blueprint_id_fails() -> None:
    with pytest.raises(ValidationError):
        _make_request(blueprint_id="")
