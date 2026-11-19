"""Tests for ModalityAffordanceCatalog — Phase 10."""
from __future__ import annotations

import pytest

from learning_pipeline.affordances.catalog import (
    ModalityAffordance,
    ModalityAffordanceCatalog,
    PlannerAffordanceView,
    _DuplicateAffordanceError,
    _UnknownAffordanceError,
)
from learning_pipeline.affordances.podcast import (
    PODCAST_AFFORDANCES,
    build_podcast_affordance_catalog,
)
from learning_pipeline.contracts.common import Modality


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_affordance(id: str, modality: Modality = Modality.PODCAST) -> ModalityAffordance:
    return ModalityAffordance(
        id=id,
        modality=modality,
        description=f"Test affordance {id}",
        pedagogical_uses=(f"use {id}",),
        suitable_narrative_roles=("explanation",),
    )


# ── Podcast affordances ─────────────────────────────────────────────────────────


def test_podcast_affordances_register() -> None:
    catalog = build_podcast_affordance_catalog()
    affordances = catalog.affordances_for(Modality.PODCAST)
    assert len(affordances) == 9


def test_all_podcast_affordance_ids_present() -> None:
    catalog = build_podcast_affordance_catalog()
    ids = catalog.ids_for(Modality.PODCAST)
    expected = {
        "spoken_hook",
        "host_expert_dialogue",
        "guided_explanation",
        "scenario_walkthrough",
        "worked_example",
        "misconception_correction",
        "guided_reflection_dialogue",
        "spoken_knowledge_check",
        "summary_recap",
    }
    assert ids == expected


def test_podcast_affordance_ordering_is_deterministic() -> None:
    catalog = build_podcast_affordance_catalog()
    first = catalog.affordances_for(Modality.PODCAST)
    second = catalog.affordances_for(Modality.PODCAST)
    assert [a.id for a in first] == [a.id for a in second]


def test_podcast_affordance_ordering_is_lexicographic() -> None:
    catalog = build_podcast_affordance_catalog()
    affordances = catalog.affordances_for(Modality.PODCAST)
    ids = [a.id for a in affordances]
    assert ids == sorted(ids)


def test_podcast_affordances_have_no_provider_details() -> None:
    for affordance in PODCAST_AFFORDANCES:
        text = (
            affordance.description
            + " ".join(affordance.pedagogical_uses)
            + " ".join(affordance.suitable_narrative_roles)
        )
        for bad in ("speech.synthesize", "audio.assemble", "litellm", "tts", "openai", "gemini"):
            assert bad not in text.lower(), (
                f"Affordance '{affordance.id}' exposes production detail '{bad}'"
            )


def test_podcast_affordances_require_no_mental_listener_response() -> None:
    catalog = build_podcast_affordance_catalog()
    combined = " ".join(
        affordance.description
        + " "
        + " ".join(affordance.pedagogical_uses)
        + " "
        + " ".join(affordance.accessibility_notes)
        for affordance in catalog.affordances_for(Modality.PODCAST)
    ).casefold()
    for prohibited in (
        "answer mentally",
        "apply a concept mentally",
        "question–pause–answer",
        "listener response",
    ):
        assert prohibited not in combined
    knowledge_check = catalog.resolve(Modality.PODCAST, "spoken_knowledge_check")
    assert "expert asks the host" in knowledge_check.description.casefold()


# ── Duplicate ID rejection ────────────────────────────────────────────────────


def test_duplicate_affordance_id_fails() -> None:
    a = _make_affordance("dup")
    b = _make_affordance("dup")
    with pytest.raises(_DuplicateAffordanceError):
        ModalityAffordanceCatalog([a, b])


def test_duplicate_id_different_modalities_allowed() -> None:
    a = _make_affordance("shared", Modality.PODCAST)
    b = _make_affordance("shared", Modality.VIDEO)
    catalog = ModalityAffordanceCatalog([a, b])
    assert catalog.resolve(Modality.PODCAST, "shared").id == "shared"
    assert catalog.resolve(Modality.VIDEO, "shared").id == "shared"


# ── Modality filtering ────────────────────────────────────────────────────────


def test_affordances_for_filters_by_modality() -> None:
    podcast_a = _make_affordance("p-a", Modality.PODCAST)
    video_a = _make_affordance("v-a", Modality.VIDEO)
    catalog = ModalityAffordanceCatalog([podcast_a, video_a])
    podcast_results = catalog.affordances_for(Modality.PODCAST)
    assert all(a.modality == Modality.PODCAST for a in podcast_results)
    assert len(podcast_results) == 1


def test_affordances_for_empty_modality_returns_empty() -> None:
    catalog = ModalityAffordanceCatalog([_make_affordance("x", Modality.PODCAST)])
    assert catalog.affordances_for(Modality.VIDEO) == ()


# ── Unknown affordance ────────────────────────────────────────────────────────


def test_resolve_unknown_affordance_fails() -> None:
    catalog = build_podcast_affordance_catalog()
    with pytest.raises(_UnknownAffordanceError):
        catalog.resolve(Modality.PODCAST, "nonexistent_affordance")


def test_resolve_known_affordance_returns_it() -> None:
    catalog = build_podcast_affordance_catalog()
    aff = catalog.resolve(Modality.PODCAST, "spoken_hook")
    assert aff.id == "spoken_hook"
    assert aff.modality == Modality.PODCAST


# ── PlannerAffordanceView ─────────────────────────────────────────────────────


def test_planner_view_affordance_ids() -> None:
    catalog = build_podcast_affordance_catalog()
    affordances = catalog.affordances_for(Modality.PODCAST)
    view = PlannerAffordanceView(modality=Modality.PODCAST, affordances=affordances)
    ids = view.affordance_ids()
    assert "spoken_hook" in ids
    assert "host_expert_dialogue" in ids


def test_planner_view_resolve_success() -> None:
    catalog = build_podcast_affordance_catalog()
    affordances = catalog.affordances_for(Modality.PODCAST)
    view = PlannerAffordanceView(modality=Modality.PODCAST, affordances=affordances)
    aff = view.resolve("guided_explanation")
    assert aff.id == "guided_explanation"


def test_planner_view_resolve_missing_raises() -> None:
    view = PlannerAffordanceView(modality=Modality.PODCAST, affordances=())
    with pytest.raises(KeyError):
        view.resolve("nonexistent")
