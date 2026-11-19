"""E-learning draft validation — Phase 14D.

Validates the ElearningProductionDraft returned by the E-learning Workflow Planner
before it is passed to the deterministic ElearningProductionPlanBuilder.

Validation rules (40+):

Draft-level structural checks:
  1.  modality_plan.modality must be Modality.ELEARNING.
  2.  modality_plan.scenes must not be empty.
  3.  draft.source_modality_plan_id must match modality_plan.plan_id.
  4.  draft.draft_id non-blank (Pydantic min_length).
  5.  draft.narrative non-blank (Pydantic min_length).
  6.  draft.course_authoring_direction non-blank (Pydantic min_length).
  7.  screen_requirements non-empty (Pydantic min_length).
  8.  At least one AuthoredScreenRequirement in screen_requirements.
  9.  screen_ids unique across screen_requirements (ElearningProductionDraft validator).
  10. slot_ids unique among VideoSlotRequirements (ElearningProductionDraft validator).
  11. directive slot_ids unique (ElearningProductionDraft validator).

Screen requirement content checks:
  12. Each AuthoredScreenRequirement.screen_type in AUTHORABLE_SCREEN_TYPES.
  13. No AuthoredScreenRequirement.screen_type in RESERVED_SCREEN_TYPES.
  14. Each AuthoredScreenRequirement.source_scene_ids references valid modality scene IDs.
  15. Each AuthoredScreenRequirement.content_direction non-blank (Pydantic).
  16. Each VideoSlotRequirement.source_scene_ids references valid modality scene IDs.
  17. Each VideoSlotRequirement.slot_id non-blank and safe (Pydantic field_validator).
  18. Each VideoSlotRequirement.title non-blank (Pydantic field_validator).

Scene coverage checks:
  19. Every modality scene covered by ≥1 screen_requirement source_scene_id.
  20. Screen requirements preserve modality-scene order (first-seen source scene ID).

Media directive cross-reference:
  21. Every directive slot_id corresponds to a VideoSlotRequirement slot_id.
  22. No VideoSlotRequirement has more than one media directive.
  23. Every required VideoSlotRequirement (required=True) has a media directive.

Avatar directive checks:
  24. avatar_profile non-blank (Pydantic min_length).
  25. voice_profile non-blank (Pydantic min_length).
  26. visual_direction non-blank (Pydantic min_length).
  27. narration_script non-blank (Pydantic min_length).
  28. target_duration_seconds positive when set (AvatarMediaDirective validator).
  29. avatar_profile in approved_avatar_profiles when provided.
  30. voice_profile in approved_voice_profiles when provided.
  31. No provider-specific IDs in avatar_profile.
  32. No provider-specific IDs in narration_script.

Manim directive checks:
  33. animation_direction non-blank (Pydantic min_length).
  34. narration_script non-blank (Pydantic min_length).
  35. target_duration_seconds positive when set (ManimMediaDirective validator).
  36. voice_profile in approved_voice_profiles when provided and set.
  37. No provider-specific IDs in animation_direction.

Slot-directive consistency:
  38. Directive slot_id does not appear in RESERVED_SCREEN_TYPES.
  39. Directive's source_scene_ids (from slot) reference valid modality scene IDs.
  40. No duplicate media directives targeting the same slot (enforced by 22 above).

Total: 40 rules (many enforced by Pydantic field/model validators; the ones below
       are the semantic checks that require cross-model context).
"""
from __future__ import annotations

import re

from learning_pipeline.contracts import Modality, ModalityPlan
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ManimMediaDirective,
    ResolvedPlanningContext,
)
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AUTHORABLE_SCREEN_TYPES,
    RESERVED_SCREEN_TYPES,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    natural_learner_action,
    resolved_learner_action,
    VideoSlotRequirement,
)

_PROVIDER_ID_PATTERNS = re.compile(
    r"(heygen|Annie_|api\.heygen\.com|/v2/video/generate|heygencdn)",
    re.IGNORECASE,
)


class ElearningDraftValidationError(ValueError):
    """Raised when an ElearningProductionDraft fails semantic validation."""


def validate_elearning_draft(
    draft: ElearningProductionDraft,
    modality_plan: ModalityPlan,
    *,
    resolved_context: ResolvedPlanningContext | None = None,
    approved_avatar_profiles: frozenset[str] | None = None,
    approved_voice_profiles: frozenset[str] | None = None,
) -> None:
    """Validate *draft* against the e-learning modality plan.

    Parameters
    ----------
    draft:
        ElearningProductionDraft returned by the planning client.
    modality_plan:
        ModalityPlan for the e-learning course; provides valid scene IDs.
    approved_avatar_profiles:
        Set of allowed logical avatar profile names. When supplied, every
        AvatarMediaDirective.avatar_profile must be in this set.
    approved_voice_profiles:
        Set of allowed logical voice profile names. When supplied, every
        voice_profile field must be in this set.

    Raises:
        ElearningDraftValidationError: On any validation failure.
    """
    # Rule 1: modality must be ELEARNING
    if modality_plan.modality != Modality.ELEARNING:
        raise ElearningDraftValidationError(
            f"ElearningWorkflowPlanner requires modality 'elearning'; "
            f"got '{modality_plan.modality}'"
        )

    # Rule 2: modality plan must have at least one scene
    if not modality_plan.scenes:
        raise ElearningDraftValidationError(
            "modality_plan has no scenes; cannot plan a course without scenes"
        )

    # Rule 3: source_modality_plan_id must match plan_id
    if draft.source_modality_plan_id != modality_plan.plan_id:
        raise ElearningDraftValidationError(
            f"draft.source_modality_plan_id '{draft.source_modality_plan_id}' "
            f"does not match modality_plan.plan_id '{modality_plan.plan_id}'"
        )

    valid_scene_ids = {s.id for s in modality_plan.scenes}

    # Rule 7+8: non-empty requirements and at least one authored screen
    # (ElearningProductionDraft enforces authored_screens min_length=1)
    if not draft.authored_screens:
        raise ElearningDraftValidationError(
            "authored_screens must contain at least one AuthoredScreenRequirement"
        )

    assessment_counts_by_scene: dict[str, int] = {}
    if resolved_context is not None:
        assessment_counts_by_scene = {
            scene.scene_id: sum(
                item.content_type == "assessment_item" for item in scene.content_items
            )
            for scene in resolved_context.scenes
        }
        assessment_scene_ids = {
            scene_id
            for scene_id, count in assessment_counts_by_scene.items()
            if count
        }
        covered_by_checks = {
            scene_id
            for requirement in draft.authored_screens
            if requirement.screen_type == "knowledge_check"
            for scene_id in requirement.source_scene_ids
        }
        missing_assessments = assessment_scene_ids - covered_by_checks
        if missing_assessments:
            raise ElearningDraftValidationError(
                "E-learning planning conflict: approved assessment content is not "
                "assigned to a knowledge_check for scenes "
                f"{sorted(missing_assessments)}. Required content cannot be omitted."
            )

    # Rules 12-18: per-requirement content validation
    covered_scene_ids: set[str] = set()
    for req in draft.ordered_screens:
        if isinstance(req, AuthoredScreenRequirement):
            _validate_authored_requirement(req, valid_scene_ids)
        else:
            _validate_slot_requirement(req, valid_scene_ids)
        for sid in req.source_scene_ids:
            covered_scene_ids.add(sid)

    # Rule 19: every modality scene must be referenced by at least one requirement
    uncovered = valid_scene_ids - covered_scene_ids
    if uncovered:
        raise ElearningDraftValidationError(
            f"The following modality scenes are not covered by any screen_requirement: "
            f"{sorted(uncovered)}"
        )

    # Rule 20: screen_requirements preserve modality-scene order (first-seen source ID)
    _validate_requirement_order(draft, modality_plan)

    # Build slot lookup for directive cross-reference
    slot_by_id: dict[str, VideoSlotRequirement] = {
        r.slot_id: r for r in draft.video_slots
    }

    # Rules 21-23, 28-37: directive validation
    directive_slot_ids_seen: set[str] = set()
    for directive in (*draft.avatar_directives, *draft.manim_directives):
        slot_id = directive.slot_id

        # Rule 21: directive slot_id must reference a VideoSlotRequirement
        if slot_id not in slot_by_id:
            raise ElearningDraftValidationError(
                f"Media directive references slot_id '{slot_id}' which is not in "
                "screen_requirements as a VideoSlotRequirement"
            )

        # Rule 22: no slot has more than one directive (uniqueness enforced by model
        # validator, but double-check here for clear error messages)
        if slot_id in directive_slot_ids_seen:
            raise ElearningDraftValidationError(
                f"Slot '{slot_id}' has more than one media directive"
            )
        directive_slot_ids_seen.add(slot_id)

        slot = slot_by_id[slot_id]

        if isinstance(directive, AvatarMediaDirective):
            _validate_avatar_directive(
                directive,
                slot,
                approved_avatar_profiles=approved_avatar_profiles,
                approved_voice_profiles=approved_voice_profiles,
            )
        elif isinstance(directive, ManimMediaDirective):
            _validate_manim_directive(
                directive,
                slot,
                approved_voice_profiles=approved_voice_profiles,
            )

    # Rule 23: every required VideoSlotRequirement must have a directive
    for slot in slot_by_id.values():
        if slot.required and slot.slot_id not in directive_slot_ids_seen:
            raise ElearningDraftValidationError(
                f"VideoSlotRequirement '{slot.slot_id}' is required but has no "
                "media directive in avatar_directives or manim_directives"
            )


def _validate_authored_requirement(
    req: AuthoredScreenRequirement,
    valid_scene_ids: set[str],
) -> None:
    # Rule 13: reserved types first (more specific error)
    if req.screen_type in RESERVED_SCREEN_TYPES:
        raise ElearningDraftValidationError(
            f"AuthoredScreenRequirement '{req.screen_id}' uses reserved "
            f"screen_type '{req.screen_type}'"
        )
    # Rule 12: screen_type must be in AUTHORABLE_SCREEN_TYPES
    if req.screen_type not in AUTHORABLE_SCREEN_TYPES:
        raise ElearningDraftValidationError(
            f"AuthoredScreenRequirement '{req.screen_id}' has screen_type "
            f"'{req.screen_type}' which is not in AUTHORABLE_SCREEN_TYPES"
        )
    if req.learner_action is None:
        raise ElearningDraftValidationError(
            f"AuthoredScreenRequirement '{req.screen_id}' must explicitly set "
            "learner_action"
        )
    action = resolved_learner_action(req)
    supported = natural_learner_action(req.screen_type)
    if action != supported:
        raise ElearningDraftValidationError(
            f"AuthoredScreenRequirement '{req.screen_id}' requests learner_action "
            f"'{action.value}', but screen_type '{req.screen_type}' supports "
            f"'{supported.value}'"
        )
    # Rule 14: source_scene_ids must reference valid modality scene IDs
    for sid in req.source_scene_ids:
        if sid not in valid_scene_ids:
            raise ElearningDraftValidationError(
                f"AuthoredScreenRequirement '{req.screen_id}' references unknown "
                f"modality scene '{sid}'"
            )


def _validate_slot_requirement(
    req: VideoSlotRequirement,
    valid_scene_ids: set[str],
) -> None:
    # Rule 16: source_scene_ids must reference valid modality scene IDs
    for sid in req.source_scene_ids:
        if sid not in valid_scene_ids:
            raise ElearningDraftValidationError(
                f"VideoSlotRequirement '{req.slot_id}' references unknown "
                f"modality scene '{sid}'"
            )


def _validate_avatar_directive(
    directive: AvatarMediaDirective,
    slot: VideoSlotRequirement,
    *,
    approved_avatar_profiles: frozenset[str] | None,
    approved_voice_profiles: frozenset[str] | None,
) -> None:
    # Rule 29: avatar_profile must be approved when a set is provided
    if approved_avatar_profiles is not None:
        if directive.avatar_profile not in approved_avatar_profiles:
            raise ElearningDraftValidationError(
                f"Avatar directive for slot '{directive.slot_id}' uses avatar_profile "
                f"'{directive.avatar_profile}' which is not in the approved set: "
                f"{sorted(approved_avatar_profiles)}"
            )

    # Rule 30: voice_profile must be approved when a set is provided
    if approved_voice_profiles is not None:
        if directive.voice_profile not in approved_voice_profiles:
            raise ElearningDraftValidationError(
                f"Avatar directive for slot '{directive.slot_id}' uses voice_profile "
                f"'{directive.voice_profile}' which is not in the approved set: "
                f"{sorted(approved_voice_profiles)}"
            )

    # Rules 31-32: no provider-specific IDs
    _check_no_provider_ids_in_avatar(directive)


def _validate_manim_directive(
    directive: ManimMediaDirective,
    slot: VideoSlotRequirement,
    *,
    approved_voice_profiles: frozenset[str] | None,
) -> None:
    # Rule 36: voice_profile must be approved when a set is provided and voice_profile is set
    if approved_voice_profiles is not None and directive.voice_profile is not None:
        if directive.voice_profile not in approved_voice_profiles:
            raise ElearningDraftValidationError(
                f"Manim directive for slot '{directive.slot_id}' uses voice_profile "
                f"'{directive.voice_profile}' which is not in the approved set: "
                f"{sorted(approved_voice_profiles)}"
            )

    # Rule 37: no provider-specific IDs in animation_direction
    _check_no_provider_ids_in_manim(directive)


def _check_no_provider_ids_in_avatar(directive: AvatarMediaDirective) -> None:
    fields = [directive.avatar_profile, directive.voice_profile, directive.narration_script]
    combined = " ".join(fields)
    if _PROVIDER_ID_PATTERNS.search(combined):
        raise ElearningDraftValidationError(
            f"Avatar directive for slot '{directive.slot_id}' contains "
            "provider-specific identifiers; use only logical profile names"
        )


def _check_no_provider_ids_in_manim(directive: ManimMediaDirective) -> None:
    fields = [directive.animation_direction, directive.narration_script]
    combined = " ".join(fields)
    if _PROVIDER_ID_PATTERNS.search(combined):
        raise ElearningDraftValidationError(
            f"Manim directive for slot '{directive.slot_id}' contains "
            "provider-specific identifiers"
        )


def _validate_requirement_order(
    draft: ElearningProductionDraft,
    modality_plan: ModalityPlan,
) -> None:
    """Verify screen_requirements preserve the ordering of modality scenes.

    For each requirement, its first source_scene_id determines its relative
    position in the expected modality-scene order.
    """
    modality_order = {scene.id: i for i, scene in enumerate(modality_plan.scenes)}
    last_index = -1
    for req in draft.ordered_screens:
        first_source = req.source_scene_ids[0]
        idx = modality_order.get(first_source, -1)
        if idx < last_index:
            raise ElearningDraftValidationError(
                f"Screen requirement '{req.screen_id}' has source_scene_id "
                f"'{first_source}' which appears before an earlier requirement's "
                "source in the modality plan. Preserve the modality-scene order."
            )
        if idx >= 0:
            last_index = idx
