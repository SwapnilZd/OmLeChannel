"""VideoModalityPlanBuilder tests — Phase 13C."""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    NarrativeRole,
    VideoModalityDraft,
    VideoSceneDraft,
)
from learning_pipeline.planners.modality.video.builder import (
    VideoModalityPlanBuilder,
    VideoModalityPlanBuilderError,
)

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-test",
  "title": "Test",
  "learner": {
    "role": "Manager", "deloitte_level": 55, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["test"], "business_context": {}
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-1", "rlo_version": "1.0", "order": 1,
      "selected_content": {"objective_ids": ["obj-1"], "concept_ids": [], "component_ids": [], "assessment_item_ids": []},
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "test",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "test", "assessment_strategy": "test",
  "estimated_duration_minutes": 10, "source_rlo_versions": {"rlo-1": "1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)

_REF = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-1",))


def _scene(**kwargs) -> VideoSceneDraft:
    defaults = dict(
        scene_id="scene-a",
        source_content=(_REF,),
        learning_objective="Understand X",
        narrative_role=NarrativeRole.EXPLANATION,
        affordance_id="avatar_led_explanation",
        teaching_pattern="direct_instruction",
        content_direction="Explain X.",
        presentation_direction="Avatar on solid background.",
        target_duration_seconds=60,
    )
    defaults.update(kwargs)
    return VideoSceneDraft(**defaults)


def _draft(*scenes: VideoSceneDraft) -> VideoModalityDraft:
    return VideoModalityDraft(
        draft_id="test-draft",
        title="Test",
        narrative="Test narrative.",
        scenes=scenes or (_scene(),),
    )


def _build(draft: VideoModalityDraft) -> ModalityPlan:
    return VideoModalityPlanBuilder().build(draft, _BLUEPRINT)


# ── Basic output ──────────────────────────────────────────────────────────────


def test_returns_modality_plan():
    plan = _build(_draft())
    assert isinstance(plan, ModalityPlan)


def test_modality_is_video():
    plan = _build(_draft())
    assert plan.modality == Modality.VIDEO


def test_plan_id_derived_from_draft_id():
    plan = _build(_draft())
    assert plan.plan_id == "mp-test-draft"


def test_narrative_preserved():
    plan = _build(_draft())
    assert plan.narrative == "Test narrative."


def test_scene_count_matches():
    plan = _build(_draft(_scene(scene_id="a"), _scene(scene_id="b")))
    assert len(plan.scenes) == 2


# ── Scene fields ──────────────────────────────────────────────────────────────


def test_scene_order_preserved():
    plan = _build(_draft(_scene(scene_id="first"), _scene(scene_id="second")))
    assert plan.scenes[0].id == "first"
    assert plan.scenes[1].id == "second"


def test_affordance_maps_to_preferred_capability():
    plan = _build(_draft(_scene(affordance_id="avatar_led_hook")))
    assert plan.scenes[0].preferred_capability == "avatar_led_hook"


def test_narrative_role_preserved():
    plan = _build(_draft(_scene(narrative_role=NarrativeRole.HOOK)))
    assert plan.scenes[0].narrative_role == "hook"


def test_source_content_preserved():
    plan = _build(_draft())
    assert plan.scenes[0].source_content[0].rlo_id == "rlo-1"


def test_learning_objective_preserved():
    plan = _build(_draft(_scene(learning_objective="Do X")))
    assert plan.scenes[0].learning_objective == "Do X"


def test_content_direction_preserved():
    plan = _build(_draft(_scene(content_direction="Teach X carefully.")))
    assert plan.scenes[0].content_direction == "Teach X carefully."


def test_presentation_direction_preserved():
    plan = _build(_draft(_scene(presentation_direction="Avatar faces camera.")))
    assert plan.scenes[0].presentation_direction == "Avatar faces camera."


def test_learner_engagement_preserved():
    plan = _build(_draft(_scene(learner_engagement="Think about X.")))
    assert plan.scenes[0].learner_engagement == "Think about X."


def test_transition_direction_preserved():
    plan = _build(_draft(_scene(transition_direction="Bridge to next scene.")))
    assert plan.scenes[0].transition_direction == "Bridge to next scene."


def test_target_duration_preserved():
    plan = _build(_draft(_scene(target_duration_seconds=90)))
    assert plan.scenes[0].target_duration_seconds == 90


def test_teaching_pattern_preserved():
    plan = _build(_draft(_scene(teaching_pattern="hook_then_rule")))
    assert plan.scenes[0].teaching_pattern == "hook_then_rule"


# ── ID sanitization ───────────────────────────────────────────────────────────


def test_scene_id_sanitized_to_lowercase():
    plan = _build(_draft(_scene(scene_id="SceneA")))
    assert plan.scenes[0].id == "scenea"


def test_scene_id_spaces_become_hyphens():
    plan = _build(_draft(_scene(scene_id="scene one")))
    assert plan.scenes[0].id == "scene-one"


# ── Error cases ───────────────────────────────────────────────────────────────


def test_duplicate_sanitized_ids_raises():
    with pytest.raises(VideoModalityPlanBuilderError, match="collision"):
        _build(_draft(_scene(scene_id="scene A"), _scene(scene_id="scene-A")))


# ── Determinism ───────────────────────────────────────────────────────────────


def test_same_draft_produces_same_plan():
    draft = _draft()
    plan1 = _build(draft)
    plan2 = _build(draft)
    assert plan1.model_dump_json() == plan2.model_dump_json()


def test_presentation_direction_absent_from_podcast_scenes():
    from learning_pipeline.contracts.modality import ModalityScene
    scene = ModalityScene(
        id="s",
        source_content=(_REF,),
        learning_objective="obj",
        teaching_pattern="direct_instruction",
        preferred_capability="guided_explanation",
        content_direction="dir",
    )
    assert scene.presentation_direction is None
