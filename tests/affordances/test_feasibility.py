"""Tests for affordance feasibility mapping — Phase 10."""
from __future__ import annotations

import pytest

from learning_pipeline.affordances.catalog import (
    ModalityAffordance,
    ModalityAffordanceCatalog,
    PlannerAffordanceView,
)
from learning_pipeline.affordances.feasibility import (
    AffordanceSupportRule,
    compute_producible_affordances,
)
from learning_pipeline.affordances.podcast import (
    PODCAST_SUPPORT_RULES,
    build_podcast_affordance_catalog,
)
from learning_pipeline.contracts.common import Modality

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


# ── All podcast affordances are producible with full capability set ────────────


def test_all_podcast_affordances_producible_when_all_caps_available() -> None:
    catalog = build_podcast_affordance_catalog()
    view = compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, _PODCAST_CAPS, Modality.PODCAST)
    assert len(view.affordances) == 9


def test_view_modality_matches_request() -> None:
    catalog = build_podcast_affordance_catalog()
    view = compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, _PODCAST_CAPS, Modality.PODCAST)
    assert view.modality == Modality.PODCAST


# ── Missing capabilities remove affordances ───────────────────────────────────


def test_missing_speech_capability_removes_all_podcast_affordances() -> None:
    catalog = build_podcast_affordance_catalog()
    view = compute_producible_affordances(
        catalog, PODCAST_SUPPORT_RULES,
        frozenset({"audio.assemble"}),  # speech missing
        Modality.PODCAST,
    )
    assert len(view.affordances) == 0


def test_missing_assembly_capability_removes_all_podcast_affordances() -> None:
    catalog = build_podcast_affordance_catalog()
    view = compute_producible_affordances(
        catalog, PODCAST_SUPPORT_RULES,
        frozenset({"speech.synthesize"}),  # assembly missing
        Modality.PODCAST,
    )
    assert len(view.affordances) == 0


def test_empty_capabilities_produces_empty_view() -> None:
    catalog = build_podcast_affordance_catalog()
    view = compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, frozenset(), Modality.PODCAST)
    assert view.affordances == ()


# ── Affordances with no matching rule are excluded ────────────────────────────


def test_affordance_with_no_rule_excluded() -> None:
    extra = ModalityAffordance(
        id="no_rule_affordance",
        modality=Modality.PODCAST,
        description="Has no support rule",
        pedagogical_uses=("test",),
    )
    catalog = ModalityAffordanceCatalog(list(build_podcast_affordance_catalog().affordances_for(Modality.PODCAST)) + [extra])
    view = compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, _PODCAST_CAPS, Modality.PODCAST)
    affordance_ids = view.affordance_ids()
    assert "no_rule_affordance" not in affordance_ids


# ── Raw task types not exposed ────────────────────────────────────────────────


def test_planner_view_contains_no_raw_task_types() -> None:
    catalog = build_podcast_affordance_catalog()
    view = compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, _PODCAST_CAPS, Modality.PODCAST)
    for aff in view.affordances:
        assert "speech.synthesize" not in aff.id
        assert "audio.assemble" not in aff.id
        assert "speech.synthesize" not in aff.description
        assert "audio.assemble" not in aff.description


# ── Support rule structure ────────────────────────────────────────────────────


def test_support_rules_cover_all_podcast_affordances() -> None:
    catalog = build_podcast_affordance_catalog()
    all_ids = catalog.ids_for(Modality.PODCAST)
    rule_ids = {r.affordance_id for r in PODCAST_SUPPORT_RULES if r.modality == Modality.PODCAST}
    assert all_ids == rule_ids


def test_support_rules_require_both_capabilities() -> None:
    for rule in PODCAST_SUPPORT_RULES:
        if rule.modality == Modality.PODCAST:
            assert "speech.synthesize" in rule.required_capabilities
            assert "audio.assemble" in rule.required_capabilities
