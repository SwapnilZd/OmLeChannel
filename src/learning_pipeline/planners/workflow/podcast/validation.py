"""
Podcast draft validation — Phase 9.

Validates the PodcastProductionDraft returned by the Workflow Planner before
it is passed to the deterministic PodcastProductionPlanBuilder.

Validation checks (in order):
  1. At least one segment.
  2. Unique, non-blank segment IDs.
  3. Every segment references at least one valid modality scene.
  4. Speaker is one of the allowed speakers for the speech capability.
  5. Spoken text is non-empty after stripping whitespace.
  6. Pause durations are non-negative.
  7. Every modality scene is covered by at least one segment, OR explicitly
     listed in omitted_scenes.
  8. default_gap_seconds is non-negative.
  9. output_filename does not contain path separators.

Failing any check raises PodcastDraftValidationError with a descriptive message.
"""
from __future__ import annotations

from learning_pipeline.contracts import ModalityPlan
from learning_pipeline.contracts.planning import PodcastProductionDraft

ALLOWED_SPEAKERS: frozenset[str] = frozenset({"Host", "Expert"})


class PodcastDraftValidationError(ValueError):
    """Raised when a PodcastProductionDraft fails semantic validation."""


def validate_podcast_draft(
    draft: PodcastProductionDraft,
    modality_plan: ModalityPlan,
    *,
    allowed_speakers: frozenset[str] = ALLOWED_SPEAKERS,
) -> None:
    """Validate *draft* against the modality plan and allowed speakers.

    Raises:
        PodcastDraftValidationError: On any validation failure.
    """
    # 1. At least one segment (already enforced by Pydantic, but checked here
    #    too so callers of validate_podcast_draft get a domain-meaningful error)
    if not draft.segments:
        raise PodcastDraftValidationError(
            f"Draft '{draft.draft_id}' has no segments"
        )

    valid_scene_ids = {scene.id for scene in modality_plan.scenes}
    seen_segment_ids: set[str] = set()

    for seg in draft.segments:
        # 2. Unique, non-blank segment IDs
        sid = seg.segment_id.strip()
        if not sid:
            raise PodcastDraftValidationError(
                "A segment has a blank segment_id"
            )
        if sid in seen_segment_ids:
            raise PodcastDraftValidationError(
                f"Duplicate segment_id: '{sid}'"
            )
        seen_segment_ids.add(sid)

        # 3. Every segment references at least one valid scene
        for scene_id in seg.source_scene_ids:
            if scene_id not in valid_scene_ids:
                raise PodcastDraftValidationError(
                    f"Segment '{seg.segment_id}' references unknown scene "
                    f"'{scene_id}' (not in modality plan)"
                )

        # 4. Speaker must be allowed
        if seg.speaker not in allowed_speakers:
            raise PodcastDraftValidationError(
                f"Segment '{seg.segment_id}' uses unsupported speaker "
                f"'{seg.speaker}'. Allowed: {sorted(allowed_speakers)}"
            )

        # 5. Non-empty text
        if not seg.text.strip():
            raise PodcastDraftValidationError(
                f"Segment '{seg.segment_id}' has blank spoken text"
            )

        # 6. Non-negative pause
        if seg.pause_after_seconds < 0:
            raise PodcastDraftValidationError(
                f"Segment '{seg.segment_id}' has negative pause_after_seconds "
                f"({seg.pause_after_seconds})"
            )

    # 7. Every modality scene is covered or explicitly omitted
    omitted_ids = {o.scene_id for o in draft.omitted_scenes}
    covered_ids = {
        scene_id
        for seg in draft.segments
        for scene_id in seg.source_scene_ids
    }
    uncovered = valid_scene_ids - covered_ids - omitted_ids
    if uncovered:
        raise PodcastDraftValidationError(
            f"The following modality scenes are not covered by any segment "
            f"and not listed in omitted_scenes: {sorted(uncovered)}"
        )

    # 8. Non-negative default gap (Pydantic enforces ge=0, but verify here)
    if draft.default_gap_seconds < 0:
        raise PodcastDraftValidationError(
            f"default_gap_seconds must be non-negative, got {draft.default_gap_seconds}"
        )

    # 9. Safe output filename
    if draft.output_filename is not None:
        name = draft.output_filename
        if any(sep in name for sep in ("/", "\\", "..")) or not name.strip():
            raise PodcastDraftValidationError(
                f"output_filename '{name}' contains path separators or is blank"
            )
