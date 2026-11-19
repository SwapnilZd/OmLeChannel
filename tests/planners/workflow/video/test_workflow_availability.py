"""
Workflow availability tests for video — Phase 13B.

Verifies:
  - VideoWorkflowPlanner is registered (workflow_planner_registered=True).
  - Video remains unavailable (modality_planner_registered=False until 13C).
  - Podcast availability is unchanged.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.format_selector.registry import build_default_registry


def test_video_workflow_planner_is_registered() -> None:
    registry = build_default_registry()
    entry = registry.entry_for(Modality.VIDEO)
    assert entry is not None
    assert entry.workflow_planner_registered is True


def test_video_modality_planner_is_registered() -> None:
    # Phase 13C: VideoModalityPlanner registered.
    registry = build_default_registry()
    entry = registry.entry_for(Modality.VIDEO)
    assert entry is not None
    assert entry.modality_planner_registered is True


def test_video_is_available_with_capability() -> None:
    # Phase 13C: both planners registered → available when capability present.
    registry = build_default_registry(
        available_capabilities=frozenset({"video.avatar.render"})
    )
    assert registry.is_available(Modality.VIDEO)


def test_podcast_remains_available() -> None:
    registry = build_default_registry(
        available_capabilities=frozenset({"speech.synthesize", "audio.assemble"})
    )
    assert registry.is_available(Modality.PODCAST)


def test_podcast_availability_unchanged() -> None:
    registry = build_default_registry(
        available_capabilities=frozenset({"speech.synthesize", "audio.assemble"})
    )
    entry = registry.entry_for(Modality.PODCAST)
    assert entry is not None
    assert entry.modality_planner_registered is True
    assert entry.workflow_planner_registered is True


def test_video_hypothetically_available_when_both_planners_registered() -> None:
    from learning_pipeline.format_selector.registry import AvailableWorkflowRegistry, WorkflowEntry

    hypothetical = AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,   # hypothetical Phase 13C
                workflow_planner_registered=True,   # Phase 13B
                required_capabilities=frozenset({"video.avatar.render"}),
            ),
        ),
        available_capabilities=frozenset({"video.avatar.render"}),
    )
    assert hypothetical.is_available(Modality.VIDEO)


def test_video_required_capability_is_avatar_render() -> None:
    registry = build_default_registry()
    entry = registry.entry_for(Modality.VIDEO)
    assert entry is not None
    assert "video.avatar.render" in entry.required_capabilities


def test_video_planner_class_exists() -> None:
    from learning_pipeline.planners.workflow.video.planner import VideoWorkflowPlanner
    assert VideoWorkflowPlanner is not None
