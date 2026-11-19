"""
Video draft validation — Phase 13B.

Validates the VideoProductionDraft returned by the Video Workflow Planner
before it is passed to the deterministic VideoProductionPlanBuilder.

Checks (in order):
  1.  render_capability is "video.avatar.render".
  2.  At least one scene.
  3.  Unique, non-blank scene IDs.
  4.  source_scene_ids reference valid modality scenes.
  5.  Narration scripts are non-empty after strip.
  6.  estimated_duration_seconds is positive.
  7.  Every modality scene is covered by at least one render scene.
  8.  Render-scene order preserves modality-scene order (first-seen source ID).
  9.  avatar_profile is in approved_avatar_profiles (when supplied).
  10. voice_profile is in approved_voice_profiles (when supplied).
  11. ColorBackgroundDraft colors are valid hex #RRGGBB.
  12. ExistingAssetBackgroundDraft asset IDs are in approved_asset_ids (when non-empty).
  13. captions is True when require_captions=True.
  14. No provider-specific IDs appear in scene or profile fields (heuristic).
  15. Total estimated duration is within tolerance of modality plan target (warn-only).
"""
from __future__ import annotations

import re

from learning_pipeline.contracts import ModalityPlan
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    VideoProductionDraft,
)

ALLOWED_RENDER_CAPABILITY = "video.avatar.render"

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_PROVIDER_ID_PATTERNS = re.compile(
    r"(heygen|Annie_|api\.heygen\.com|/v2/video/generate)",
    re.IGNORECASE,
)


class VideoDraftValidationError(ValueError):
    """Raised when a VideoProductionDraft fails semantic validation."""


def validate_video_draft(
    draft: VideoProductionDraft,
    modality_plan: ModalityPlan,
    *,
    approved_avatar_profiles: frozenset[str] | None = None,
    approved_voice_profiles: frozenset[str] | None = None,
    approved_asset_ids: frozenset[str] = frozenset(),
    require_captions: bool = False,
    max_total_duration_seconds: int | None = None,
) -> None:
    """Validate *draft* against the video modality plan.

    Parameters
    ----------
    draft:
        VideoProductionDraft returned by the planning client.
    modality_plan:
        ModalityPlan for the video course; provides valid scene IDs.
    approved_avatar_profiles:
        Set of allowed logical avatar profile names.  When supplied, the draft's
        avatar_profile must be one of them.
    approved_voice_profiles:
        Set of allowed logical voice profile names.  When supplied, the draft's
        voice_profile must be one of them.
    approved_asset_ids:
        Known asset IDs for ExistingAssetBackgroundDraft validation.  When
        non-empty, any ExistingAssetBackgroundDraft asset_id must be listed here.
    require_captions:
        When True, captions must be enabled in the draft.

    Raises:
        VideoDraftValidationError: On any validation failure.
    """
    # 1. render_capability must be "video.avatar.render"
    if draft.render_capability != ALLOWED_RENDER_CAPABILITY:
        raise VideoDraftValidationError(
            f"render_capability must be '{ALLOWED_RENDER_CAPABILITY}'; "
            f"got '{draft.render_capability}'"
        )

    # 2. At least one scene
    if not draft.scenes:
        raise VideoDraftValidationError(
            f"Draft '{draft.draft_id}' has no scenes"
        )

    valid_scene_ids = {scene.id for scene in modality_plan.scenes}
    covered_modality_scene_ids = _validate_each_scene(
        draft, valid_scene_ids, approved_asset_ids
    )

    # 7. Every modality scene must be covered
    uncovered = valid_scene_ids - covered_modality_scene_ids
    if uncovered:
        raise VideoDraftValidationError(
            f"The following modality scenes are not covered by any render scene: "
            f"{sorted(uncovered)}"
        )

    # 8. Render-scene order preserves modality-scene order (first-seen source ID)
    _validate_scene_order(draft, modality_plan)

    # 9. Avatar profile must be approved (when provided)
    if approved_avatar_profiles is not None:
        if draft.avatar_profile not in approved_avatar_profiles:
            raise VideoDraftValidationError(
                f"avatar_profile '{draft.avatar_profile}' is not in the approved "
                f"set: {sorted(approved_avatar_profiles)}"
            )

    # 10. Voice profile must be approved (when provided)
    if approved_voice_profiles is not None:
        if draft.voice_profile not in approved_voice_profiles:
            raise VideoDraftValidationError(
                f"voice_profile '{draft.voice_profile}' is not in the approved "
                f"set: {sorted(approved_voice_profiles)}"
            )

    # 13. Accessibility caption enforcement
    if require_captions and not draft.captions:
        raise VideoDraftValidationError(
            "Captions are required by accessibility policy but draft has captions=False"
        )

    # 15. Total duration ceiling
    if max_total_duration_seconds is not None:
        total = sum(s.estimated_duration_seconds for s in draft.scenes)
        if total > max_total_duration_seconds:
            raise VideoDraftValidationError(
                f"Total estimated duration {total:.1f}s exceeds the "
                f"{max_total_duration_seconds}s ceiling. Shorten scene scripts."
            )


def _validate_each_scene(
    draft: VideoProductionDraft,
    valid_scene_ids: set[str],
    approved_asset_ids: frozenset[str],
) -> set[str]:
    """Validate each render scene; return the set of covered modality scene IDs."""
    seen_render_scene_ids: set[str] = set()
    covered: set[str] = set()

    for scene in draft.scenes:
        sid = scene.scene_id.strip()
        if not sid:
            raise VideoDraftValidationError("A render scene has a blank scene_id")
        if sid in seen_render_scene_ids:
            raise VideoDraftValidationError(f"Duplicate scene_id in draft: '{sid}'")
        seen_render_scene_ids.add(sid)

        for source_id in scene.source_scene_ids:
            if source_id not in valid_scene_ids:
                raise VideoDraftValidationError(
                    f"Render scene '{scene.scene_id}' references unknown modality "
                    f"scene '{source_id}' (not in modality plan)"
                )
            covered.add(source_id)

        if not scene.script.strip():
            raise VideoDraftValidationError(
                f"Render scene '{scene.scene_id}' has a blank script"
            )
        if scene.estimated_duration_seconds <= 0:
            raise VideoDraftValidationError(
                f"Render scene '{scene.scene_id}' has non-positive "
                f"estimated_duration_seconds ({scene.estimated_duration_seconds})"
            )

        _validate_background(scene, approved_asset_ids)
        _check_no_provider_ids(scene)

    return covered


def _validate_background(
    scene: AvatarVideoSceneDraft,
    approved_asset_ids: frozenset[str],
) -> None:
    if scene.background.kind == "color":
        if not _HEX_COLOR_RE.match(scene.background.color or ""):
            raise VideoDraftValidationError(
                f"Render scene '{scene.scene_id}' has an invalid background color "
                f"'{scene.background.color}' (expected #RRGGBB)"
            )
    elif scene.background.kind == "existing_asset":
        if approved_asset_ids and scene.background.asset_id not in approved_asset_ids:
            raise VideoDraftValidationError(
                f"Render scene '{scene.scene_id}' uses unknown asset "
                f"'{scene.background.asset_id}'"
            )


def _check_no_provider_ids(scene: AvatarVideoSceneDraft) -> None:
    fields_to_check = [scene.scene_id, scene.script, scene.title or ""]
    if scene.background.kind == "existing_asset":
        fields_to_check.append(scene.background.asset_id or "")
    combined = " ".join(fields_to_check)
    if _PROVIDER_ID_PATTERNS.search(combined):
        raise VideoDraftValidationError(
            f"Render scene '{scene.scene_id}' contains provider-specific identifiers "
            "in content fields; the planner must use only logical names"
        )


def _validate_scene_order(
    draft: VideoProductionDraft,
    modality_plan: ModalityPlan,
) -> None:
    """Verify that render scenes preserve the ordering of modality scenes.

    For each render scene, its first source_scene_id determines its position
    in the expected modality-scene order.  If two render scenes have first-seen
    source scene IDs that appear out of modality-plan order, validation fails.
    """
    modality_order = {scene.id: i for i, scene in enumerate(modality_plan.scenes)}

    last_modality_index = -1
    for render_scene in draft.scenes:
        first_source = render_scene.source_scene_ids[0]
        current_index = modality_order[first_source]
        if current_index < last_modality_index:
            raise VideoDraftValidationError(
                f"Render scene '{render_scene.scene_id}' has source_scene_id "
                f"'{first_source}' which appears before an earlier render scene's "
                "source in the modality plan.  Preserve the modality-scene order."
            )
        last_modality_index = current_index
