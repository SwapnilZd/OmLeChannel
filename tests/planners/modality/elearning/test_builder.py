"""ElearningModalityPlanBuilder tests — Phase 14E.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  - Valid draft produces a ModalityPlan with ELEARNING modality.
  - Scene IDs are sanitized to lowercase alphanumeric + hyphens.
  - affordance_id maps to preferred_capability in ModalityScene.
  - narrative_role is preserved.
  - learner_engagement is preserved when set.
  - plan_id is prefixed with mp-.
  - Duplicate sanitized IDs raise.
  - Deterministic: same draft → same plan.
"""
from __future__ import annotations

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    ElearningModalityDraft,
    ElearningSceneDraft,
    NarrativeRole,
)
from learning_pipeline.planners.modality.elearning.builder import (
    ElearningModalityPlanBuilder,
    ElearningModalityPlanBuilderError,
)

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-builder-test",
  "title": "Builder Test",
  "learner": {
    "role": "Analyst", "deloitte_level": 45, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["test"], "business_context": {}
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-1", "rlo_version": "1.0", "order": 1,
      "selected_content": {"objective_ids": ["obj-1"], "concept_ids": [], "component_ids": [], "assessment_item_ids": []},
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "core",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "test", "assessment_strategy": "formative",
  "estimated_duration_minutes": 5, "source_rlo_versions": {"rlo-1": "1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)
_BUILDER = ElearningModalityPlanBuilder()
_REF = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-1",))


def _scene(
    scene_id: str,
    affordance: str = "elearning.static_explanation",
    narrative_role: NarrativeRole = NarrativeRole.EXPLANATION,
    engagement: str | None = None,
) -> ElearningSceneDraft:
    return ElearningSceneDraft(
        scene_id=scene_id,
        source_content=(_REF,),
        learning_objective="Understand the concept.",
        narrative_role=narrative_role,
        affordance_id=affordance,
        teaching_pattern="direct_instruction",
        content_direction="Explain clearly.",
        learner_engagement=engagement,
        target_duration_seconds=60,
    )


def _draft(*scene_ids: str) -> ElearningModalityDraft:
    return ElearningModalityDraft(
        draft_id="builder-test",
        title="Builder Test",
        narrative="A test narrative.",
        scenes=tuple(_scene(sid) for sid in scene_ids),
    )


# ── Basic build ────────────────────────────────────────────────────────────────


def test_build_returns_modality_plan() -> None:
    plan = _BUILDER.build(_draft("scene-intro"), _BLUEPRINT)
    assert isinstance(plan, ModalityPlan)


def test_plan_modality_is_elearning() -> None:
    plan = _BUILDER.build(_draft("scene-intro"), _BLUEPRINT)
    assert plan.modality == Modality.ELEARNING


def test_plan_id_prefixed() -> None:
    plan = _BUILDER.build(_draft("scene-intro"), _BLUEPRINT)
    assert plan.plan_id.startswith("mp-")


def test_plan_id_contains_draft_id() -> None:
    plan = _BUILDER.build(_draft("scene-intro"), _BLUEPRINT)
    assert "builder-test" in plan.plan_id


def test_scene_count_matches() -> None:
    plan = _BUILDER.build(_draft("scene-a", "scene-b"), _BLUEPRINT)
    assert len(plan.scenes) == 2


# ── ID sanitization ───────────────────────────────────────────────────────────


def test_scene_id_sanitized_to_lowercase() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(_scene("SCENE-INTRO"),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].id == "scene-intro"


def test_scene_id_special_chars_replaced() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(_scene("Scene Intro!!"),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].id == "scene-intro"


def test_scene_id_collision_raises() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(
            _scene("SCENE-INTRO"),
            _scene("scene intro"),  # both sanitize to "scene-intro"
        ),
    )
    with pytest.raises(ElearningModalityPlanBuilderError, match="collision"):
        _BUILDER.build(draft, _BLUEPRINT)


# ── Field mapping ─────────────────────────────────────────────────────────────


def test_affordance_id_maps_to_preferred_capability() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(_scene("s1", affordance="elearning.guided_practice"),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].preferred_capability == "elearning.guided_practice"


def test_narrative_role_preserved() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(_scene("s1", narrative_role=NarrativeRole.SUMMARY),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].narrative_role == "summary"


def test_learner_engagement_preserved_when_set() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(_scene("s1", engagement="flip cards"),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].learner_engagement == "flip cards"


def test_learner_engagement_none_when_unset() -> None:
    draft = ElearningModalityDraft(
        draft_id="test", title="T", narrative="N.",
        scenes=(_scene("s1", engagement=None),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].learner_engagement is None


def test_source_content_preserved() -> None:
    plan = _BUILDER.build(_draft("s1"), _BLUEPRINT)
    assert plan.scenes[0].source_content[0].rlo_id == "rlo-1"


def test_target_duration_preserved() -> None:
    plan = _BUILDER.build(_draft("s1"), _BLUEPRINT)
    assert plan.scenes[0].target_duration_seconds == 60


def test_content_direction_preserved() -> None:
    plan = _BUILDER.build(_draft("s1"), _BLUEPRINT)
    assert "Explain" in plan.scenes[0].content_direction


# ── Determinism ───────────────────────────────────────────────────────────────


def test_same_draft_produces_same_plan() -> None:
    draft = _draft("s1", "s2")
    plan1 = _BUILDER.build(draft, _BLUEPRINT)
    plan2 = _BUILDER.build(draft, _BLUEPRINT)
    assert plan1.model_dump_json() == plan2.model_dump_json()


# ── All affordances produce valid scenes ──────────────────────────────────────


@pytest.mark.parametrize("affordance_id", [
    "elearning.orientation",
    "elearning.objective_preview",
    "elearning.static_explanation",
    "elearning.guided_example",
    "elearning.guided_practice",
    "elearning.knowledge_check",
    "elearning.assessment",
    "elearning.reflection",
    "elearning.summary",
    "elearning.avatar_framing",
    "elearning.avatar_explanation",
    "elearning.animated_demonstration",
    "elearning.animated_explanation",
])
def test_affordance_maps_correctly(affordance_id: str) -> None:
    draft = ElearningModalityDraft(
        draft_id="aff-test", title="T", narrative="N.",
        scenes=(_scene("s1", affordance=affordance_id),),
    )
    plan = _BUILDER.build(draft, _BLUEPRINT)
    assert plan.scenes[0].preferred_capability == affordance_id
