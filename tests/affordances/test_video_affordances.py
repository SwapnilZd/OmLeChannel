"""Video affordance catalog tests — Phase 13C."""
from __future__ import annotations

import pytest

from learning_pipeline.affordances.video import (
    VIDEO_AFFORDANCES,
    VIDEO_SUPPORT_RULES,
    build_video_affordance_catalog,
)
from learning_pipeline.affordances.feasibility import compute_producible_affordances
from learning_pipeline.contracts.common import Modality

_EXPECTED_IDS = frozenset({
    "avatar_led_hook",
    "avatar_led_orientation",
    "avatar_led_explanation",
    "avatar_with_existing_visual",
    "avatar_led_scenario",
    "avatar_led_worked_example",
    "avatar_led_misconception_correction",
    "avatar_led_reflection",
    "avatar_led_knowledge_check",
    "avatar_led_recap",
})

_VIDEO_CAP = frozenset({"video.avatar.render"})
_VIDEO_CAP_WITH_ASSET = frozenset({"video.avatar.render", "visual_asset_available"})


# ── Affordance registration ────────────────────────────────────────────────────


def test_all_video_affordances_registered():
    catalog = build_video_affordance_catalog()
    ids = catalog.ids_for(Modality.VIDEO)
    assert ids == _EXPECTED_IDS


def test_no_duplicate_affordance_ids():
    seen: list[str] = []
    for a in VIDEO_AFFORDANCES:
        assert a.id not in seen, f"Duplicate: {a.id}"
        seen.append(a.id)


def test_all_affordances_are_video_modality():
    for a in VIDEO_AFFORDANCES:
        assert a.modality == Modality.VIDEO


def test_affordances_deterministic_order():
    catalog = build_video_affordance_catalog()
    affordances = catalog.affordances_for(Modality.VIDEO)
    ids = [a.id for a in affordances]
    assert ids == sorted(ids)


def test_affordances_planner_safe_serialization():
    catalog = build_video_affordance_catalog()
    from learning_pipeline.affordances.catalog import PlannerAffordanceView
    view = PlannerAffordanceView(
        modality=Modality.VIDEO,
        affordances=catalog.affordances_for(Modality.VIDEO),
    )
    dumped = view.model_dump_json()
    assert "video.avatar.render" not in dumped
    assert "heygen" not in dumped.lower()
    assert "api_key" not in dumped.lower()


# ── Task type names not used as affordance IDs ─────────────────────────────────


def test_no_capability_names_as_affordance_ids():
    import re
    cap_pattern = re.compile(r"^[a-z_]+\.[a-z_]+")
    for a in VIDEO_AFFORDANCES:
        assert not cap_pattern.match(a.id), (
            f"Affordance ID '{a.id}' looks like a production capability name"
        )


# ── Feasibility mapping ───────────────────────────────────────────────────────


def test_avatar_led_affordances_require_avatar_render():
    avatar_only_ids = _EXPECTED_IDS - {"avatar_with_existing_visual"}
    for rule in VIDEO_SUPPORT_RULES:
        if rule.affordance_id in avatar_only_ids:
            assert "video.avatar.render" in rule.required_capabilities


def test_existing_visual_requires_asset_capability():
    for rule in VIDEO_SUPPORT_RULES:
        if rule.affordance_id == "avatar_with_existing_visual":
            assert "visual_asset_available" in rule.required_capabilities


def test_avatar_only_affordances_producible_without_assets():
    catalog = build_video_affordance_catalog()
    view = compute_producible_affordances(
        catalog, VIDEO_SUPPORT_RULES, _VIDEO_CAP, Modality.VIDEO
    )
    ids = view.affordance_ids()
    assert "avatar_with_existing_visual" not in ids
    # All other avatar affordances should be present
    assert ids == _EXPECTED_IDS - {"avatar_with_existing_visual"}


def test_existing_visual_affordance_included_when_assets_available():
    catalog = build_video_affordance_catalog()
    view = compute_producible_affordances(
        catalog, VIDEO_SUPPORT_RULES, _VIDEO_CAP_WITH_ASSET, Modality.VIDEO
    )
    assert "avatar_with_existing_visual" in view.affordance_ids()
    assert view.affordance_ids() == _EXPECTED_IDS


def test_no_affordances_without_avatar_render_capability():
    catalog = build_video_affordance_catalog()
    view = compute_producible_affordances(
        catalog, VIDEO_SUPPORT_RULES, frozenset(), Modality.VIDEO
    )
    assert len(view.affordances) == 0


def test_animation_affordances_not_exposed():
    catalog = build_video_affordance_catalog()
    view = compute_producible_affordances(
        catalog, VIDEO_SUPPORT_RULES, _VIDEO_CAP_WITH_ASSET, Modality.VIDEO
    )
    ids = view.affordance_ids()
    assert "custom_animation" not in ids
    assert "generated_diagram" not in ids
    assert "interactive_simulation" not in ids
    assert "dynamic_code_demonstration" not in ids


def test_production_details_not_in_affordance_view():
    catalog = build_video_affordance_catalog()
    view = compute_producible_affordances(
        catalog, VIDEO_SUPPORT_RULES, _VIDEO_CAP, Modality.VIDEO
    )
    dumped = view.model_dump_json()
    assert "Annie_expressive_public" not in dumped
    assert "330290724a1b470fb63153f34d4c0183" not in dumped
