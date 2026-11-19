"""Video modality planner registry activation tests — Phase 13C."""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.format_selector.registry import (
    AvailableWorkflowRegistry,
    WorkflowEntry,
    build_default_registry,
)

_AVATAR_CAPS = frozenset({"video.avatar.render"})
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


# ── Both planners registered in default registry ──────────────────────────────


def test_video_modality_planner_is_registered() -> None:
    reg = build_default_registry()
    entry = reg.entry_for(Modality.VIDEO)
    assert entry is not None
    assert entry.modality_planner_registered is True


def test_video_workflow_planner_is_registered() -> None:
    reg = build_default_registry()
    entry = reg.entry_for(Modality.VIDEO)
    assert entry is not None
    assert entry.workflow_planner_registered is True


def test_video_is_available_with_capability() -> None:
    reg = build_default_registry(available_capabilities=_AVATAR_CAPS)
    assert reg.is_available(Modality.VIDEO) is True


def test_video_is_unavailable_without_capability() -> None:
    reg = build_default_registry(available_capabilities=frozenset())
    assert reg.is_available(Modality.VIDEO) is False


# ── Activation semantics ──────────────────────────────────────────────────────


def test_video_unavailable_when_only_modality_planner_registered() -> None:
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


def test_video_unavailable_when_only_workflow_planner_registered() -> None:
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


def test_video_available_when_both_planners_and_capability() -> None:
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


# ── Podcast is unaffected ─────────────────────────────────────────────────────


def test_podcast_availability_unaffected_by_video_planner_registration() -> None:
    reg = build_default_registry(available_capabilities=_PODCAST_CAPS)
    assert reg.is_available(Modality.PODCAST) is True
    assert reg.is_available(Modality.VIDEO) is False
