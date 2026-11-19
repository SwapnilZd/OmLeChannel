"""
ElearningModalityPlanBuilder — Phase 14E.

Deterministically converts a validated ElearningModalityDraft into a ModalityPlan.

The builder:
  - sanitizes scene IDs to safe alphanumeric-and-hyphen strings;
  - preserves scene order from the draft;
  - maps affordance_id → preferred_capability (pedagogical affordance value);
  - populates narrative_role, learner_engagement;
  - computes a deterministic plan_id from the draft_id.

Given the same ElearningModalityDraft, it always produces the same ModalityPlan.
No LLM calls are made here.
"""
from __future__ import annotations

import re

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, ModalityScene
from learning_pipeline.contracts.planning import ElearningModalityDraft


class ElearningModalityPlanBuilderError(ValueError):
    """Raised when a draft cannot be converted to a ModalityPlan."""


_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _sanitize_scene_id(scene_id: str) -> str:
    """Normalize a scene ID to lowercase alphanumeric + hyphens/underscores."""
    sanitized = _SAFE_ID_RE.sub("-", scene_id.strip()).strip("-")
    sanitized = sanitized.lower()
    if not sanitized:
        raise ElearningModalityPlanBuilderError(
            f"Scene ID {scene_id!r} produces an empty sanitized ID"
        )
    return sanitized


class ElearningModalityPlanBuilder:
    """Convert a validated ElearningModalityDraft into a ModalityPlan.

    Deterministic: same draft + same blueprint → same ModalityPlan JSON.
    """

    def build(
        self,
        draft: ElearningModalityDraft,
        blueprint: CourseBlueprint,
    ) -> ModalityPlan:
        """Build and return a ModalityPlan.

        Parameters
        ----------
        draft:
            A validated ElearningModalityDraft from the Modality Planner.
        blueprint:
            The CourseBlueprint; used only to namespace the plan_id.

        Raises:
            ElearningModalityPlanBuilderError: If any scene ID sanitizes to empty
                or produces a collision.
        """
        seen_ids: dict[str, str] = {}
        scenes: list[ModalityScene] = []

        for scene_draft in draft.scenes:
            safe_id = _sanitize_scene_id(scene_draft.scene_id)
            if safe_id in seen_ids:
                raise ElearningModalityPlanBuilderError(
                    f"Scene ID collision: '{scene_draft.scene_id}' and "
                    f"'{seen_ids[safe_id]}' both map to '{safe_id}'"
                )
            seen_ids[safe_id] = scene_draft.scene_id

            scenes.append(ModalityScene(
                id=safe_id,
                source_content=scene_draft.source_content,
                learning_objective=scene_draft.learning_objective,
                teaching_pattern=scene_draft.teaching_pattern,
                preferred_capability=scene_draft.affordance_id,
                acceptable_fallbacks=(),
                content_direction=scene_draft.content_direction,
                target_duration_seconds=scene_draft.target_duration_seconds,
                narrative_role=scene_draft.narrative_role.value,
                learner_engagement=scene_draft.learner_engagement,
            ))

        return ModalityPlan(
            plan_id=f"mp-{draft.draft_id}",
            modality=Modality.ELEARNING,
            narrative=draft.narrative,
            scenes=tuple(scenes),
        )
