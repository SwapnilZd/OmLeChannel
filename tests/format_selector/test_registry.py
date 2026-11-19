"""AvailableWorkflowRegistry tests — Phase 11."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.common import Modality
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)

_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})
_VIDEO_CAPS = frozenset({"video.render"})
_HTML_CAPS = frozenset({"html.compile"})


def _podcast_entry(*, disabled: bool = False, planner: bool = True, workflow: bool = True) -> WorkflowEntry:
    return WorkflowEntry(
        modality=Modality.PODCAST,
        modality_planner_registered=planner,
        workflow_planner_registered=workflow,
        required_capabilities=frozenset({"speech.synthesize", "audio.assemble"}),
        disabled=disabled,
    )


def _make_registry(
    *entries: WorkflowEntry,
    caps: frozenset[str] = frozenset(),
) -> AvailableWorkflowRegistry:
    return AvailableWorkflowRegistry(entries=entries, available_capabilities=caps)


# ── Fully registered workflow is available ────────────────────────────────────


def test_fully_registered_podcast_is_available() -> None:
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is True


def test_available_modalities_includes_podcast_when_registered() -> None:
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    assert Modality.PODCAST in reg.available_modalities()


# ── Missing modality planner makes workflow unavailable ───────────────────────


def test_missing_modality_planner_makes_unavailable() -> None:
    reg = _make_registry(_podcast_entry(planner=False), caps=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is False


def test_missing_modality_planner_blocker_in_snapshot() -> None:
    reg = _make_registry(_podcast_entry(planner=False), caps=_PODCAST_CAPS)
    snap = reg.snapshot()
    assert snap["podcast"]["available"] is False
    assert snap["podcast"]["modality_planner_registered"] is False


# ── Missing workflow planner makes unavailable ────────────────────────────────


def test_missing_workflow_planner_makes_unavailable() -> None:
    reg = _make_registry(_podcast_entry(workflow=False), caps=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is False


# ── Missing production capability makes unavailable ───────────────────────────


def test_missing_capability_makes_podcast_unavailable() -> None:
    reg = _make_registry(_podcast_entry(), caps=frozenset({"speech.synthesize"}))
    assert reg.is_available(Modality.PODCAST) is False


def test_all_caps_present_makes_podcast_available() -> None:
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is True


# ── Disabled workflow is unavailable ─────────────────────────────────────────


def test_disabled_workflow_is_unavailable() -> None:
    reg = _make_registry(_podcast_entry(disabled=True), caps=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is False


# ── Unregistered modality ─────────────────────────────────────────────────────


def test_unregistered_modality_is_not_available() -> None:
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    assert reg.is_available(Modality.VIDEO) is False


def test_entry_for_returns_none_for_unregistered() -> None:
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    assert reg.entry_for(Modality.VIDEO) is None


# ── Available modalities ordering is deterministic ────────────────────────────


def test_available_modalities_deterministic_order() -> None:
    video = WorkflowEntry(
        modality=Modality.VIDEO,
        modality_planner_registered=True,
        workflow_planner_registered=True,
        required_capabilities=_VIDEO_CAPS,
    )
    html = WorkflowEntry(
        modality=Modality.ELEARNING,
        modality_planner_registered=True,
        workflow_planner_registered=True,
        required_capabilities=_HTML_CAPS,
    )
    reg = _make_registry(
        html, video, _podcast_entry(),
        caps=_PODCAST_CAPS | _VIDEO_CAPS | _HTML_CAPS,
    )
    result = reg.available_modalities()
    expected = tuple(m for m in Modality)  # enum declaration order
    assert result == expected


# ── Default registry ──────────────────────────────────────────────────────────


def test_default_registry_podcast_available_with_caps() -> None:
    reg = build_default_registry(available_capabilities=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is True


def test_default_registry_podcast_unavailable_without_caps() -> None:
    reg = build_default_registry()
    assert reg.is_available(Modality.PODCAST) is False


def test_default_registry_video_unavailable() -> None:
    reg = build_default_registry(available_capabilities=_VIDEO_CAPS)
    assert reg.is_available(Modality.VIDEO) is False


def test_default_registry_elearning_unavailable() -> None:
    reg = build_default_registry(available_capabilities=_HTML_CAPS)
    assert reg.is_available(Modality.ELEARNING) is False


# ── Snapshot ──────────────────────────────────────────────────────────────────


def test_snapshot_contains_all_registered_modalities() -> None:
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    snap = reg.snapshot()
    assert "podcast" in snap


def test_snapshot_is_serializable_to_json() -> None:
    import json
    reg = _make_registry(_podcast_entry(), caps=_PODCAST_CAPS)
    snap = reg.snapshot()
    json.dumps(snap)  # must not raise
