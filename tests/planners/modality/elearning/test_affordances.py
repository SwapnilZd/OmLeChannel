"""E-learning affordance catalog tests — Phase 14E.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  1.  E-learning affordance definitions load.
  2.  Affordance IDs are unique within the catalog.
  3.  Core static affordances are feasible with author capability alone.
  4.  Avatar affordance is removed when avatar capability is unavailable.
  5.  Manim affordance is removed when Manim capability is unavailable.
  6.  Optional video capability loss does not disable static e-learning affordances.
  7.  Missing course author disables all affordances.
  8.  Planner-facing affordances do not expose provider internals.
  9.  All affordance IDs use two-segment dot notation (not three-segment capability IDs).
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.common import Modality
from learning_pipeline.affordances.elearning import (
    CAP_AVATAR_RENDER,
    CAP_ELEARNING_AUTHOR,
    CAP_MANIM_RENDER,
    ELEARNING_SUPPORT_RULES,
    build_elearning_affordance_catalog,
)
from learning_pipeline.affordances.feasibility import compute_producible_affordances

_STATIC_CAPS = frozenset({CAP_ELEARNING_AUTHOR})
_FULL_CAPS = frozenset({CAP_ELEARNING_AUTHOR, CAP_AVATAR_RENDER, CAP_MANIM_RENDER})

_CATALOG = build_elearning_affordance_catalog()

_STATIC_AFFORDANCE_IDS = {
    "elearning.orientation",
    "elearning.objective_preview",
    "elearning.static_explanation",
    "elearning.guided_example",
    "elearning.guided_practice",
    "elearning.knowledge_check",
    "elearning.assessment",
    "elearning.reflection",
    "elearning.summary",
}
_AVATAR_AFFORDANCE_IDS = {"elearning.avatar_framing", "elearning.avatar_explanation"}
_MANIM_AFFORDANCE_IDS = {"elearning.animated_demonstration", "elearning.animated_explanation"}


# ── 1: Catalog loads ──────────────────────────────────────────────────────────


def test_elearning_affordances_load() -> None:
    assert _CATALOG is not None
    affordances = _CATALOG.affordances_for(Modality.ELEARNING)
    assert len(affordances) > 0


def test_avatar_affordances_position_video_as_brief_supporting_media() -> None:
    affordances = {
        item.id: item for item in _CATALOG.affordances_for(Modality.ELEARNING)
    }

    assert "brief presenter interlude" in affordances["elearning.avatar_framing"].description
    assert "authored screens carry the substantive explanation" in (
        affordances["elearning.avatar_explanation"].description
    )


# ── 2: Unique IDs ─────────────────────────────────────────────────────────────


def test_affordance_ids_are_unique() -> None:
    affordances = _CATALOG.affordances_for(Modality.ELEARNING)
    ids = [a.id for a in affordances]
    assert len(ids) == len(set(ids))


# ── 3: Static affordances feasible with author only ────────────────────────────


def test_static_affordances_feasible_with_author_only() -> None:
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, _STATIC_CAPS, Modality.ELEARNING
    )
    feasible = view.affordance_ids()
    assert _STATIC_AFFORDANCE_IDS.issubset(feasible)


# ── 4: Avatar affordance removed without avatar cap ───────────────────────────


def test_avatar_affordance_removed_without_avatar_cap() -> None:
    caps = frozenset({CAP_ELEARNING_AUTHOR, CAP_MANIM_RENDER})
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING
    )
    feasible = view.affordance_ids()
    for avatar_id in _AVATAR_AFFORDANCE_IDS:
        assert avatar_id not in feasible


def test_avatar_affordance_present_with_avatar_cap() -> None:
    caps = frozenset({CAP_ELEARNING_AUTHOR, CAP_AVATAR_RENDER})
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING
    )
    feasible = view.affordance_ids()
    assert _AVATAR_AFFORDANCE_IDS.issubset(feasible)


# ── 5: Manim affordance removed without Manim cap ─────────────────────────────


def test_manim_affordance_removed_without_manim_cap() -> None:
    caps = frozenset({CAP_ELEARNING_AUTHOR, CAP_AVATAR_RENDER})
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING
    )
    feasible = view.affordance_ids()
    for manim_id in _MANIM_AFFORDANCE_IDS:
        assert manim_id not in feasible


def test_manim_affordance_present_with_manim_cap() -> None:
    caps = frozenset({CAP_ELEARNING_AUTHOR, CAP_MANIM_RENDER})
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING
    )
    feasible = view.affordance_ids()
    assert _MANIM_AFFORDANCE_IDS.issubset(feasible)


def test_manim_affordances_include_business_structure_and_progressive_builds() -> None:
    affordances = {
        item.id: item for item in _CATALOG.affordances_for(Modality.ELEARNING)
    }
    demonstration = affordances["elearning.animated_demonstration"]
    explanation = affordances["elearning.animated_explanation"]

    assert any("progressive construction" in use for use in demonstration.pedagogical_uses)
    assert "structured business frameworks" in explanation.description


# ── 6: Optional video loss does not disable static e-learning ─────────────────


def test_optional_video_loss_keeps_static_affordances() -> None:
    for caps in [
        frozenset({CAP_ELEARNING_AUTHOR}),
        frozenset({CAP_ELEARNING_AUTHOR, CAP_AVATAR_RENDER}),
        frozenset({CAP_ELEARNING_AUTHOR, CAP_MANIM_RENDER}),
    ]:
        view = compute_producible_affordances(
            _CATALOG, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING
        )
        assert _STATIC_AFFORDANCE_IDS.issubset(view.affordance_ids()), \
            f"Static affordances missing for caps: {caps}"


# ── 7: Missing course author disables all affordances ─────────────────────────


def test_missing_author_disables_all_affordances() -> None:
    caps = frozenset({CAP_AVATAR_RENDER, CAP_MANIM_RENDER})
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING
    )
    assert len(view.affordance_ids()) == 0


def test_no_capabilities_yields_no_affordances() -> None:
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, frozenset(), Modality.ELEARNING
    )
    assert len(view.affordance_ids()) == 0


# ── 8: No provider internals in planner-facing affordances ────────────────────


_PROVIDER_KEYWORDS = {
    "heygen", "annie_", "manim_scene", "docker", "api_key", "HEYGEN_API_KEY",
    "litellm", "openai", "voice_id", "avatar_id",
}


def test_no_provider_internals_in_affordances() -> None:
    view = compute_producible_affordances(
        _CATALOG, ELEARNING_SUPPORT_RULES, _FULL_CAPS, Modality.ELEARNING
    )
    view_json = view.model_dump_json().lower()
    for keyword in _PROVIDER_KEYWORDS:
        assert keyword.lower() not in view_json, \
            f"Provider internal '{keyword}' found in planner affordance view"


# ── 9: Two-segment affordance IDs (not three-segment capability IDs) ──────────


def test_affordance_ids_are_two_segment() -> None:
    affordances = _CATALOG.affordances_for(Modality.ELEARNING)
    for aff in affordances:
        parts = aff.id.split(".")
        assert len(parts) == 2, (
            f"Affordance '{aff.id}' has {len(parts)} segments; "
            "e-learning affordances must use two-segment IDs (elearning.name)"
        )


def test_all_support_rules_reference_known_affordances() -> None:
    catalog_ids = {a.id for a in _CATALOG.affordances_for(Modality.ELEARNING)}
    for rule in ELEARNING_SUPPORT_RULES:
        assert rule.affordance_id in catalog_ids, \
            f"Support rule references unknown affordance '{rule.affordance_id}'"
