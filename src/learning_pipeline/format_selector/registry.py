"""Available workflow registry — Phase 11 / Phase 13B / Phase 13C / Phase 14E.

A modality is advertised as available only when its full production path is
registered: Modality Planner, Workflow Planner, required capabilities, and no
explicit disable flag.

After Phase 14E:
  - podcast: fully available (modality planner + workflow planner).
  - video: fully available (VideoModalityPlanner + VideoWorkflowPlanner both registered).
  - e-learning: fully available (ElearningModalityPlanner + ElearningWorkflowPlanner).

E-learning required capabilities: elearning.course.author + elearning.bundle.assemble.
Avatar and Manim are optional — their absence removes those affordances but does not
disable the modality.
"""
from __future__ import annotations

from typing import Any

from learning_pipeline.contracts.common import FrozenModel, Modality


class WorkflowEntry(FrozenModel):
    """Registration record for one modality's planning and execution support."""

    modality: Modality
    modality_planner_registered: bool
    workflow_planner_registered: bool
    required_capabilities: frozenset[str]
    disabled: bool = False


class AvailableWorkflowRegistry:
    """Reports which modality workflows are currently deployable.

    A modality is available when:
    - its entry is present and not disabled;
    - both planners are registered;
    - all required production capabilities are in the supplied capability set.
    """

    def __init__(
        self,
        entries: tuple[WorkflowEntry, ...],
        available_capabilities: frozenset[str] = frozenset(),
    ) -> None:
        self._entries: dict[Modality, WorkflowEntry] = {e.modality: e for e in entries}
        self._available_capabilities = available_capabilities

    def is_available(self, modality: Modality) -> bool:
        entry = self._entries.get(modality)
        if entry is None:
            return False
        if entry.disabled:
            return False
        if not entry.modality_planner_registered:
            return False
        if not entry.workflow_planner_registered:
            return False
        return entry.required_capabilities.issubset(self._available_capabilities)

    def available_modalities(self) -> tuple[Modality, ...]:
        return tuple(m for m in Modality if self.is_available(m))

    def entry_for(self, modality: Modality) -> WorkflowEntry | None:
        return self._entries.get(modality)

    def snapshot(self) -> dict[str, Any]:
        """Serializable snapshot of the registry state for hashing and persistence."""
        return {
            m.value: {
                "modality_planner_registered": e.modality_planner_registered,
                "workflow_planner_registered": e.workflow_planner_registered,
                "required_capabilities": sorted(e.required_capabilities),
                "disabled": e.disabled,
                "available": self.is_available(m),
            }
            for m, e in sorted(self._entries.items(), key=lambda kv: kv[0].value)
        }


def build_default_registry(
    available_capabilities: frozenset[str] = frozenset(),
) -> AvailableWorkflowRegistry:
    """Return the default registry for the current deployment.

    Podcast: fully available (both planners registered).
    Video: fully available after Phase 13C (both planners registered).
    E-learning: fully available after Phase 14E (both planners registered).

    E-learning required capabilities are the two baseline tools:
      elearning.course.author  — courses are authored
      elearning.bundle.assemble — courses are packaged

    video.avatar.render and video.manim.render are optional — their absence
    removes those affordances but does not make the modality unavailable.
    """
    return AvailableWorkflowRegistry(
        entries=(
            WorkflowEntry(
                modality=Modality.PODCAST,
                modality_planner_registered=True,
                workflow_planner_registered=True,
                required_capabilities=frozenset({"speech.synthesize", "audio.assemble"}),
            ),
            WorkflowEntry(
                modality=Modality.VIDEO,
                modality_planner_registered=True,    # VideoModalityPlanner: Phase 13C ✓
                workflow_planner_registered=True,    # VideoWorkflowPlanner: Phase 13B ✓
                required_capabilities=frozenset({"video.avatar.render"}),
            ),
            WorkflowEntry(
                modality=Modality.ELEARNING,
                modality_planner_registered=True,    # ElearningModalityPlanner: Phase 14E ✓
                workflow_planner_registered=True,    # ElearningWorkflowPlanner: Phase 14D ✓
                required_capabilities=frozenset({
                    "elearning.course.author",
                    "elearning.bundle.assemble",
                }),
            ),
        ),
        available_capabilities=available_capabilities,
    )
