"""Video workflow availability tests — Phase 13A.

Verifies that:
- video.avatar.render is registered in the tool catalog.
- The video workflow remains UNAVAILABLE until both planners are registered
  (Phases 13B/C). This is intentional — the executors exist but the full
  pipeline path is not yet wired.
- Podcast availability is unaffected by video capability registration.
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts.common import Modality
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)

_AVATAR_CAPS = frozenset({"video.avatar.render"})
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


# ── video.avatar.render is in the tool catalog ────────────────────────────────


def test_avatar_video_capability_in_tool_catalog():
    from learning_pipeline.config import build_tool_catalog
    catalog = build_tool_catalog()
    assert "video.avatar.render" in catalog.capabilities


def test_avatar_video_registered_task_type():
    from learning_pipeline.config import REGISTERED_TASK_TYPES
    assert "video.avatar.render" in REGISTERED_TASK_TYPES


# ── Default registry: video unavailable until planners exist ──────────────────


def test_default_registry_video_available_with_capability():
    # Phase 13C: both planners registered → video is available when capability present.
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    assert reg.is_available(Modality.VIDEO) is True


def test_default_registry_video_entry_exists():
    reg = build_default_registry()
    entry = reg.entry_for(Modality.VIDEO)
    assert entry is not None


def test_default_registry_video_entry_requires_avatar_render_capability():
    reg = build_default_registry()
    entry = reg.entry_for(Modality.VIDEO)
    assert "video.avatar.render" in entry.required_capabilities


def test_default_registry_video_both_planners_registered():
    # Phase 13C: both VideoModalityPlanner and VideoWorkflowPlanner registered.
    reg = build_default_registry()
    entry = reg.entry_for(Modality.VIDEO)
    assert entry.modality_planner_registered is True   # Phase 13C complete
    assert entry.workflow_planner_registered is True   # Phase 13B complete


def test_default_registry_video_snapshot_reports_available():
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    snap = reg.snapshot()
    assert snap["video"]["available"] is True           # Phase 13C: fully available
    assert snap["video"]["modality_planner_registered"] is True
    assert snap["video"]["workflow_planner_registered"] is True


def test_default_registry_video_in_available_modalities():
    # Phase 13C: video is now available when the capability is present.
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    assert Modality.VIDEO in reg.available_modalities()


# ── When planners exist (hypothetical 13B/C state) ───────────────────────────


def test_video_available_when_planners_and_capability_present():
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=_AVATAR_CAPS,
            ),
        ),
        available_capabilities=_AVATAR_CAPS,
    )
    assert reg.is_available(Modality.VIDEO) is True


def test_video_unavailable_when_planners_present_but_capability_missing():
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=_AVATAR_CAPS,
            ),
        ),
        available_capabilities=frozenset(),
    )
    assert reg.is_available(Modality.VIDEO) is False


def test_video_unavailable_when_capability_present_but_workflow_planner_missing():
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,
                workflow_planner_registered=False,
                required_capabilities=_AVATAR_CAPS,
            ),
        ),
        available_capabilities=_AVATAR_CAPS,
    )
    assert reg.is_available(Modality.VIDEO) is False


def test_video_unavailable_when_capability_present_but_modality_planner_missing():
    reg = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=False,
                workflow_planner_registered=True,
                required_capabilities=_AVATAR_CAPS,
            ),
        ),
        available_capabilities=_AVATAR_CAPS,
    )
    assert reg.is_available(Modality.VIDEO) is False


# ── Podcast is unaffected ─────────────────────────────────────────────────────


def test_podcast_available_with_correct_caps_regardless_of_video():
    reg = build_default_registry(
        available_capabilities=_PODCAST_CAPS | _AVATAR_CAPS
    )
    assert reg.is_available(Modality.PODCAST) is True


def test_podcast_unavailable_without_speech_caps_even_with_video_caps():
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    assert reg.is_available(Modality.PODCAST) is False


def test_both_podcast_and_video_caps_present_both_available():
    # Phase 13C: both modalities are fully available when capabilities are present.
    reg = build_default_registry(
        available_capabilities=_PODCAST_CAPS | _AVATAR_CAPS
    )
    available = reg.available_modalities()
    assert Modality.PODCAST in available
    assert Modality.VIDEO in available
