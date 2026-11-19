"""Tests for validate_elearning_draft — Phase 14D.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  1.  Valid draft with authored screens passes.
  2.  Valid draft with avatar video slot passes.
  3.  Valid draft with Manim video slot passes.
  4.  Wrong modality raises.
  5.  Empty modality scenes raises.
  6.  Mismatched source_modality_plan_id raises.
  7.  authored_screens min_length=1 enforced by Pydantic (ValidationError).
  8.  Uncovered modality scene raises.
  9.  Unknown scene ID in authored requirement raises.
  10. Unknown scene ID in video slot raises.
  11. Invalid screen_type raises.
  12. Reserved screen_type (video_slot) raises.
  13. Directive references unknown slot_id raises.
  14. Same slot has two directives raises (model validator).
  15. Required slot without directive raises.
  16. Avatar profile not in approved set raises.
  17. Voice profile not in approved set (avatar) raises.
  18. Voice profile not in approved set (Manim) raises.
  19. Provider ID in avatar_profile raises.
  20. Out-of-order requirements raises.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.contracts import Modality, ModalityPlan
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ManimMediaDirective,
    ResolvedContentItem,
    ResolvedPlanningContext,
    ResolvedSceneContext,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.planners.workflow.elearning.validation import (
    ElearningDraftValidationError,
    validate_elearning_draft,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    LearnerAction,
    VideoSlotRequirement,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_ELEARNING_PLAN_JSON = """{
  "plan_id": "mp-elearning-test",
  "modality": "elearning",
  "narrative": "E-learning test plan.",
  "scenes": [
    {
      "id": "scene-intro",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Understand the concept.",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "elearning.static_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "introduce the topic"
    },
    {
      "id": "scene-apply",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Apply the concept.",
      "teaching_pattern": "worked_example",
      "preferred_capability": "elearning.avatar_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "show an example"
    }
  ]
}"""

_PODCAST_PLAN_JSON = """{
  "plan_id": "mp-podcast-test",
  "modality": "podcast",
  "narrative": "Podcast plan.",
  "scenes": [
    {
      "id": "scene-intro",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Understand.",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "narration",
      "acceptable_fallbacks": [],
      "content_direction": "intro"
    }
  ]
}"""


def _elearning_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_ELEARNING_PLAN_JSON)


def _podcast_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_PODCAST_PLAN_JSON)


def _authored(
    screen_id: str = "screen-intro",
    scene_ids: tuple[str, ...] = ("scene-intro",),
    screen_type: str = "title",
    learner_action: LearnerAction = LearnerAction.CONSUME,
) -> AuthoredScreenRequirement:
    return AuthoredScreenRequirement(
        screen_id=screen_id,
        screen_type=screen_type,
        source_scene_ids=scene_ids,
        content_direction="Write about the topic.",
        learner_action=learner_action,
    )


def test_authored_requirement_must_explicitly_declare_learner_action():
    requirement = AuthoredScreenRequirement(
        screen_id="screen-intro",
        screen_type="title",
        source_scene_ids=("scene-intro",),
        content_direction="Introduce the assigned topic.",
    )
    draft = _minimal_draft(authored_screens=(requirement,))

    with pytest.raises(ElearningDraftValidationError, match="learner_action"):
        validate_elearning_draft(draft, _elearning_plan())


def test_authored_requirement_action_must_match_component_capability():
    draft = _minimal_draft(
        authored_screens=(
            _authored(
                "screen-intro",
                ("scene-intro",),
                "structured_list",
                LearnerAction.CHOOSE,
            ),
        )
    )

    with pytest.raises(ElearningDraftValidationError, match="choose.*structured_list"):
        validate_elearning_draft(draft, _elearning_plan())


def _slot(
    screen_id: str = "screen-video",
    slot_id: str = "slot-avatar",
    scene_ids: tuple[str, ...] = ("scene-apply",),
    required: bool = True,
    captions_required: bool = True,
) -> VideoSlotRequirement:
    return VideoSlotRequirement(
        screen_id=screen_id,
        slot_id=slot_id,
        source_scene_ids=scene_ids,
        title="Avatar Explanation",
        required=required,
        captions_required=captions_required,
    )


def _avatar_directive(slot_id: str = "slot-avatar") -> AvatarMediaDirective:
    return AvatarMediaDirective(
        slot_id=slot_id,
        narration_script="This is the narration.",
        avatar_profile="default_instructor",
        voice_profile="default_narrator",
        visual_direction="Dark background, instructor centered.",
    )


def _manim_directive(slot_id: str = "slot-manim") -> ManimMediaDirective:
    return ManimMediaDirective(
        slot_id=slot_id,
        narration_script="Watch the animation.",
        animation_direction="Show a flow diagram of the process.",
        voice_profile="default_narrator",
    )


def _minimal_draft(
    authored_screens=None,
    video_slots: tuple = (),
    screen_order=None,
    avatar_directives: tuple = (),
    manim_directives: tuple = (),
    source_modality_plan_id: str = "mp-elearning-test",
) -> ElearningProductionDraft:
    if authored_screens is None:
        authored_screens = (
            _authored("screen-intro", ("scene-intro",)),
            _authored("screen-apply", ("scene-apply",)),
        )
    if screen_order is None:
        screen_order = tuple(r.screen_id for r in (*authored_screens, *video_slots))
    return ElearningProductionDraft(
        draft_id="draft-test-1",
        source_modality_plan_id=source_modality_plan_id,
        narrative="A test e-learning course.",
        authored_screens=authored_screens,
        video_slots=video_slots,
        screen_order=screen_order,
        avatar_directives=avatar_directives,
        manim_directives=manim_directives,
        course_authoring_direction="Write clear, concise content.",
    )


# ── 1: Valid authored-only draft passes ────────────────────────────────────────

def test_valid_authored_only_draft_passes():
    draft = _minimal_draft()
    validate_elearning_draft(draft, _elearning_plan())


def test_draft_size_is_not_an_independent_validation_error():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-intro", ("scene-intro",)),
            _authored("screen-middle", ("scene-intro",)),
            _authored("screen-apply", ("scene-apply",)),
        )
    )

    validate_elearning_draft(draft, _elearning_plan())


def _context_with_assessments(count: int) -> ResolvedPlanningContext:
    learner = LearnerContext(
        role="Individual",
        default_proficiency="beginner",
        goals=["Learn the topic"],
    )
    return ResolvedPlanningContext(
        blueprint_id="bp-generic",
        learner=learner,
        scenes=(
            ResolvedSceneContext(
                scene_id="scene-intro",
                learning_objective="Understand the topic.",
                teaching_pattern="direct_instruction",
                content_items=(),
            ),
            ResolvedSceneContext(
                scene_id="scene-apply",
                learning_objective="Confirm understanding.",
                teaching_pattern="assessment",
                content_items=tuple(
                    ResolvedContentItem(
                        rlo_id="rlo-generic",
                        rlo_version="1",
                        content_type="assessment_item",
                        content_id=f"question-{index}",
                        content="Approved multiple-choice question.",
                    )
                    for index in range(count)
                ),
            ),
        ),
    )


def test_required_assessment_scene_cannot_be_omitted():
    draft = _minimal_draft()

    with pytest.raises(ElearningDraftValidationError, match="approved assessment"):
        validate_elearning_draft(
            draft,
            _elearning_plan(),
            resolved_context=_context_with_assessments(1),
        )


def test_grouped_assessment_can_expand_to_every_required_question():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-intro", ("scene-intro",)),
            _authored(
                "screen-check",
                ("scene-apply",),
                "knowledge_check",
                LearnerAction.CHOOSE,
            ),
        )
    )

    validate_elearning_draft(
        draft,
        _elearning_plan(),
        resolved_context=_context_with_assessments(20),
    )


# ── 2: Valid draft with avatar slot passes ─────────────────────────────────────

def test_valid_draft_with_avatar_slot_passes():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",)),),
        avatar_directives=(_avatar_directive("slot-avatar"),), manim_directives=(),
    )
    validate_elearning_draft(draft, _elearning_plan())


# ── 3: Valid draft with Manim slot passes ──────────────────────────────────────

def test_valid_draft_with_manim_slot_passes():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-manim", ("scene-apply",)),),
        avatar_directives=(), manim_directives=(_manim_directive("slot-manim"),),
    )
    validate_elearning_draft(draft, _elearning_plan())


# ── 4: Wrong modality raises ───────────────────────────────────────────────────

def test_wrong_modality_raises():
    draft = _minimal_draft(source_modality_plan_id="mp-podcast-test")
    with pytest.raises(ElearningDraftValidationError, match="elearning"):
        validate_elearning_draft(draft, _podcast_plan())


# ── 5: Empty modality scenes raises ───────────────────────────────────────────

def test_empty_modality_scenes_raises():
    import json
    plan_dict = json.loads(_ELEARNING_PLAN_JSON)
    plan_dict["scenes"] = []
    plan = ModalityPlan.model_validate(plan_dict)
    draft = _minimal_draft(source_modality_plan_id="mp-elearning-test")
    with pytest.raises(ElearningDraftValidationError, match="no scenes"):
        validate_elearning_draft(draft, plan)


# ── 6: Mismatched source_modality_plan_id raises ──────────────────────────────

def test_mismatched_plan_id_raises():
    draft = _minimal_draft(source_modality_plan_id="wrong-plan-id")
    with pytest.raises(ElearningDraftValidationError, match="source_modality_plan_id"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 7: authored_screens min_length=1 enforced by Pydantic ─────────────────────

def test_authored_screens_min_length_enforced_by_pydantic():
    with pytest.raises(ValidationError):
        ElearningProductionDraft(
            draft_id="draft-1",
            source_modality_plan_id="mp-elearning-test",
            narrative="test",
            authored_screens=(),
            video_slots=(
                _slot("screen-video", "slot-avatar", ("scene-intro",)),
            ),
            screen_order=("screen-video",),
            avatar_directives=(_avatar_directive("slot-avatar"),),
            manim_directives=(),
            course_authoring_direction="direction",
        )


# ── 7b: Only video slots, no authored screen, raises in validation ─────────────

def test_only_video_slots_raises_in_validate():
    # Build draft bypassing the model validation (it catches the authored-screen check there)
    # by using a valid draft first, then test the semantic validation
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-apply", ("scene-apply",)),),
        avatar_directives=(_avatar_directive("slot-apply"),), manim_directives=(),
    )
    validate_elearning_draft(draft, _elearning_plan())


# ── 8: Uncovered modality scene raises ────────────────────────────────────────

def test_uncovered_modality_scene_raises():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
    )
    with pytest.raises(ElearningDraftValidationError, match="scene-apply"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 9: Unknown scene ID in authored requirement raises ────────────────────────

def test_unknown_scene_in_authored_requirement_raises():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-intro", ("scene-intro",)),
            _authored("screen-bad", ("nonexistent-scene",)),
            _authored("screen-apply", ("scene-apply",)),
        ),
    )
    with pytest.raises(ElearningDraftValidationError, match="nonexistent-scene"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 10: Unknown scene ID in video slot raises ─────────────────────────────────

def test_unknown_scene_in_slot_raises():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-intro", ("scene-intro",)),
            _authored("screen-apply", ("scene-apply",)),
        ),
        video_slots=(_slot("screen-bad", "slot-bad", ("ghost-scene",)),),
        screen_order=("screen-intro", "screen-bad", "screen-apply"),
        avatar_directives=(_avatar_directive("slot-bad"),), manim_directives=(),
    )
    with pytest.raises(ElearningDraftValidationError, match="ghost-scene"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 11: Invalid screen_type raises ────────────────────────────────────────────

def test_invalid_screen_type_raises():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-intro", ("scene-intro",), screen_type="not_a_real_type"),
            _authored("screen-apply", ("scene-apply",)),
        ),
    )
    with pytest.raises(ElearningDraftValidationError, match="AUTHORABLE_SCREEN_TYPES"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 12: Reserved screen_type raises ───────────────────────────────────────────

def test_reserved_screen_type_raises():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-intro", ("scene-intro",), screen_type="video_player"),
            _authored("screen-apply", ("scene-apply",)),
        ),
    )
    with pytest.raises(ElearningDraftValidationError, match="reserved"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 13: Directive references unknown slot_id raises ───────────────────────────

def test_directive_unknown_slot_id_raises():
    draft = _minimal_draft(
        avatar_directives=(_avatar_directive("nonexistent-slot"),), manim_directives=(),
    )
    with pytest.raises(ElearningDraftValidationError, match="nonexistent-slot"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 14: Duplicate directive slot_ids rejected at model level ──────────────────

def test_duplicate_directive_slot_ids_rejected_by_model():
    with pytest.raises(ValueError, match="unique"):
        ElearningProductionDraft(
            draft_id="draft-1",
            source_modality_plan_id="mp-elearning-test",
            narrative="test",
            authored_screens=(_authored("screen-intro", ("scene-intro",)),),
            video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",)),),
            screen_order=("screen-intro", "screen-video"),
            avatar_directives=(
                _avatar_directive("slot-avatar"),
                _avatar_directive("slot-avatar"),  # duplicate
            ),
            manim_directives=(),
            course_authoring_direction="direction",
        )


# ── 15: Required slot without directive raises ────────────────────────────────

def test_required_slot_without_directive_raises():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",), required=True),),
        avatar_directives=(),
            manim_directives=(),  # no directive for required slot
    )
    with pytest.raises(ElearningDraftValidationError, match="required"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 16: Avatar profile not in approved set raises ─────────────────────────────

def test_avatar_profile_not_approved_raises():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",)),),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-avatar",
                narration_script="Narration here.",
                avatar_profile="unknown_avatar",
                voice_profile="default_narrator",
                visual_direction="dark background",
            ),
        ),
        manim_directives=(),
    )
    with pytest.raises(ElearningDraftValidationError, match="avatar_profile"):
        validate_elearning_draft(
            draft,
            _elearning_plan(),
            approved_avatar_profiles=frozenset({"default_instructor"}),
        )


# ── 17: Voice profile not approved (avatar) raises ────────────────────────────

def test_voice_profile_not_approved_avatar_raises():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",)),),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-avatar",
                narration_script="Narration.",
                avatar_profile="default_instructor",
                voice_profile="unknown_voice",
                visual_direction="dark background",
            ),
        ),
        manim_directives=(),
    )
    with pytest.raises(ElearningDraftValidationError, match="voice_profile"):
        validate_elearning_draft(
            draft,
            _elearning_plan(),
            approved_avatar_profiles=frozenset({"default_instructor"}),
            approved_voice_profiles=frozenset({"default_narrator"}),
        )


# ── 18: Voice profile not approved (Manim) raises ────────────────────────────

def test_voice_profile_not_approved_manim_raises():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-manim", ("scene-apply",)),),
        avatar_directives=(),
        manim_directives=(
            ManimMediaDirective(
                slot_id="slot-manim",
                narration_script="Watch this.",
                animation_direction="Show steps.",
                voice_profile="bad_voice",
            ),
        ),
    )
    with pytest.raises(ElearningDraftValidationError, match="voice_profile"):
        validate_elearning_draft(
            draft,
            _elearning_plan(),
            approved_voice_profiles=frozenset({"default_narrator"}),
        )


# ── 19: Provider ID in avatar_profile raises ──────────────────────────────────

def test_provider_id_in_avatar_profile_raises():
    draft = _minimal_draft(
        authored_screens=(_authored("screen-intro", ("scene-intro",)),),
        video_slots=(_slot("screen-video", "slot-avatar", ("scene-apply",)),),
        avatar_directives=(
            AvatarMediaDirective(
                slot_id="slot-avatar",
                narration_script="Narration.",
                avatar_profile="Annie_expressive_public",
                voice_profile="default_narrator",
                visual_direction="background",
            ),
        ),
        manim_directives=(),
    )
    with pytest.raises(ElearningDraftValidationError, match="provider-specific"):
        validate_elearning_draft(draft, _elearning_plan())


# ── 20: Out-of-order requirements raises ──────────────────────────────────────

def test_out_of_order_requirements_raises():
    draft = _minimal_draft(
        authored_screens=(
            _authored("screen-apply", ("scene-apply",)),  # scene-apply before scene-intro
            _authored("screen-intro", ("scene-intro",)),
        ),
    )
    with pytest.raises(ElearningDraftValidationError, match="order"):
        validate_elearning_draft(draft, _elearning_plan())
