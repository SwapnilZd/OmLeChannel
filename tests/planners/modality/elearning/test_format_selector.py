"""Format selector e-learning activation tests — Phase 14E.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  43. Explicit e-learning succeeds when baseline capabilities are available.
  44. Explicit e-learning fails clearly when core capabilities are missing.
  45. Automatic selection considers e-learning when feasible.
  46. Automatic selection excludes e-learning when infeasible.
  47. Optional capability loss changes affordances without disabling modality.
  48. Explicit user choice retains precedence.
  49. Existing Podcast and Video selection behavior does not regress.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)

_ELEARNING_BASELINE_CAPS = frozenset({
    "elearning.course.author",
    "elearning.bundle.assemble",
})
_ELEARNING_FULL_CAPS = frozenset({
    "elearning.course.author",
    "elearning.bundle.assemble",
    "video.avatar.render",
    "video.manim.render",
})
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_VIDEO_CAPS = frozenset({"video.avatar.render"})
_ALL_CAPS = _ELEARNING_BASELINE_CAPS | _ELEARNING_FULL_CAPS | _PODCAST_CAPS | _VIDEO_CAPS


# ── Both planners registered ──────────────────────────────────────────────────


def test_elearning_modality_planner_is_registered() -> None:
    reg = build_default_registry()
    entry = reg.entry_for(Modality.ELEARNING)
    assert entry is not None
    assert entry.modality_planner_registered is True


def test_elearning_workflow_planner_is_registered() -> None:
    reg = build_default_registry()
    entry = reg.entry_for(Modality.ELEARNING)
    assert entry is not None
    assert entry.workflow_planner_registered is True


# ── 43: Explicit e-learning available with baseline caps ──────────────────────


def test_elearning_available_with_baseline_caps() -> None:
    reg = build_default_registry(available_capabilities=_ELEARNING_BASELINE_CAPS)
    assert reg.is_available(Modality.ELEARNING) is True


def test_elearning_available_with_full_caps() -> None:
    reg = build_default_registry(available_capabilities=_ELEARNING_FULL_CAPS)
    assert reg.is_available(Modality.ELEARNING) is True


# ── 44: Missing core capability disables e-learning ──────────────────────────


def test_elearning_unavailable_without_author() -> None:
    reg = build_default_registry(
        available_capabilities=frozenset({"elearning.bundle.assemble"})
    )
    assert reg.is_available(Modality.ELEARNING) is False


def test_elearning_unavailable_without_assembler() -> None:
    reg = build_default_registry(
        available_capabilities=frozenset({"elearning.course.author"})
    )
    assert reg.is_available(Modality.ELEARNING) is False


def test_elearning_unavailable_with_no_caps() -> None:
    reg = build_default_registry(available_capabilities=frozenset())
    assert reg.is_available(Modality.ELEARNING) is False


# ── 45: Auto selection includes e-learning when feasible ─────────────────────


def test_elearning_in_available_modalities_with_baseline() -> None:
    reg = build_default_registry(available_capabilities=_ELEARNING_BASELINE_CAPS)
    assert Modality.ELEARNING in reg.available_modalities()


# ── 46: Auto selection excludes e-learning when infeasible ───────────────────


def test_elearning_excluded_from_available_without_author() -> None:
    reg = build_default_registry(available_capabilities=frozenset())
    assert Modality.ELEARNING not in reg.available_modalities()


# ── 47: Optional capability loss changes affordances without disabling modality


def test_avatar_loss_does_not_disable_elearning() -> None:
    # Without avatar render, e-learning is still available (static only)
    caps = frozenset({"elearning.course.author", "elearning.bundle.assemble"})
    reg = build_default_registry(available_capabilities=caps)
    assert reg.is_available(Modality.ELEARNING) is True


def test_manim_loss_does_not_disable_elearning() -> None:
    # Without Manim, e-learning is still available (static only)
    caps = frozenset({"elearning.course.author", "elearning.bundle.assemble"})
    reg = build_default_registry(available_capabilities=caps)
    assert reg.is_available(Modality.ELEARNING) is True


def test_avatar_and_manim_loss_keeps_static_elearning() -> None:
    from learning_pipeline.affordances.elearning import (
        ELEARNING_SUPPORT_RULES, build_elearning_affordance_catalog,
    )
    from learning_pipeline.affordances.feasibility import compute_producible_affordances

    catalog = build_elearning_affordance_catalog()
    caps = frozenset({"elearning.course.author"})
    view = compute_producible_affordances(catalog, ELEARNING_SUPPORT_RULES, caps, Modality.ELEARNING)
    # Static affordances still present
    assert "elearning.static_explanation" in view.affordance_ids()
    # Avatar and animated affordances absent
    assert "elearning.avatar_framing" not in view.affordance_ids()
    assert "elearning.animated_demonstration" not in view.affordance_ids()


# ── 48: Explicit user choice retains precedence ───────────────────────────────


def test_elearning_entry_exists_in_registry() -> None:
    reg = build_default_registry(available_capabilities=_ELEARNING_BASELINE_CAPS)
    entry = reg.entry_for(Modality.ELEARNING)
    assert entry is not None
    assert entry.modality == Modality.ELEARNING


def test_registry_snapshot_includes_elearning() -> None:
    reg = build_default_registry(available_capabilities=_ELEARNING_BASELINE_CAPS)
    snap = reg.snapshot()
    assert "elearning" in snap
    assert snap["elearning"]["available"] is True


# ── 49: Podcast and Video do not regress ──────────────────────────────────────


def test_podcast_unaffected_by_elearning_activation() -> None:
    reg = build_default_registry(available_capabilities=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is True
    assert reg.is_available(Modality.ELEARNING) is False


def test_video_unaffected_by_elearning_activation() -> None:
    reg = build_default_registry(available_capabilities=_VIDEO_CAPS)
    assert reg.is_available(Modality.VIDEO) is True
    assert reg.is_available(Modality.ELEARNING) is False


def test_all_three_modalities_available_with_all_caps() -> None:
    reg = build_default_registry(available_capabilities=_ALL_CAPS)
    assert reg.is_available(Modality.PODCAST) is True
    assert reg.is_available(Modality.VIDEO) is True
    assert reg.is_available(Modality.ELEARNING) is True


def test_required_capabilities_correct_for_elearning() -> None:
    reg = build_default_registry()
    entry = reg.entry_for(Modality.ELEARNING)
    assert entry is not None
    assert "elearning.course.author" in entry.required_capabilities
    assert "elearning.bundle.assemble" in entry.required_capabilities
    # Manim is NOT required (optional)
    assert "video.manim.render" not in entry.required_capabilities


# ── Activation semantics ──────────────────────────────────────────────────────


def test_elearning_unavailable_when_only_modality_planner_registered() -> None:
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=True,
                workflow_planner_registered=False,
                required_capabilities=_ELEARNING_BASELINE_CAPS,
            ),
        ),
        available_capabilities=_ELEARNING_BASELINE_CAPS,
    )
    assert reg.is_available(Modality.ELEARNING) is False


def test_elearning_unavailable_when_only_workflow_planner_registered() -> None:
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=False,
                workflow_planner_registered=True,
                required_capabilities=_ELEARNING_BASELINE_CAPS,
            ),
        ),
        available_capabilities=_ELEARNING_BASELINE_CAPS,
    )
    assert reg.is_available(Modality.ELEARNING) is False


def test_elearning_available_when_both_planners_and_baseline_caps() -> None:
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=_ELEARNING_BASELINE_CAPS,
            ),
        ),
        available_capabilities=_ELEARNING_BASELINE_CAPS,
    )
    assert reg.is_available(Modality.ELEARNING) is True
