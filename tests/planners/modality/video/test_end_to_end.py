"""End-to-end VideoModalityPlanner → ModalityPlan tests — Phase 13C."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    ModalityPlanningContext,
    NarrativeRole,
    ResolvedRLOContext,
    VideoModalityDraft,
    VideoSceneDraft,
)
from learning_pipeline.affordances.catalog import ModalityAffordanceCatalog, PlannerAffordanceView
from learning_pipeline.affordances.video import VIDEO_AFFORDANCES
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.modality.video.planner import VideoModalityPlanner

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-e2e",
  "title": "ADKAR Change Leadership",
  "learner": {
    "role": "Manager", "deloitte_level": 55, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["lead change effectively"],
    "business_context": {}
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-adkar-01", "rlo_version": "1.1.0", "order": 1,
      "selected_content": {
        "objective_ids": ["lo-01"],
        "concept_ids": ["c-01"],
        "component_ids": [],
        "assessment_item_ids": []
      },
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "direct",
      "personalization_rationale": "core model",
      "sequencing_rationale": "foundational",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "linear", "assessment_strategy": "embedded",
  "estimated_duration_minutes": 12,
  "source_rlo_versions": {"rlo-adkar-01": "1.1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)

_RLO_CTX = ResolvedRLOContext(
    rlo_id="rlo-adkar-01", rlo_version="1.1.0", order=1,
    title="ADKAR Model", topic="Change Leadership",
    terminal_objective_text="Apply ADKAR to a change initiative.",
    enabling_objectives=(), concepts=(), components=(), assessment_items=(),
    selected_objective_ids=("lo-01",), selected_concept_ids=("c-01",),
    selected_component_ids=(), selected_assessment_ids=(),
    role_relevance="direct", example_context=None, adaptation_instructions=(),
)

_CONTEXT = ModalityPlanningContext(
    blueprint_id="bp-e2e",
    learner=_BLUEPRINT.learner,
    rlo_contexts=(_RLO_CTX,),
)

_CATALOG = ModalityAffordanceCatalog(VIDEO_AFFORDANCES)
_AFFORDANCE_VIEW = PlannerAffordanceView(
    modality=Modality.VIDEO,
    affordances=_CATALOG.affordances_for(Modality.VIDEO),
)

_REF = RLOContentRef(
    rlo_id="rlo-adkar-01", rlo_version="1.1.0",
    objective_ids=("lo-01",), concept_ids=("c-01",),
)


def _two_scene_draft() -> VideoModalityDraft:
    return VideoModalityDraft(
        draft_id="e2e-adkar-draft",
        title="ADKAR Change Leadership",
        narrative="An avatar-led introduction to the ADKAR model for managers.",
        scenes=(
            VideoSceneDraft(
                scene_id="hook",
                source_content=(_REF,),
                learning_objective="Recognise why change often fails without ADKAR",
                narrative_role=NarrativeRole.HOOK,
                affordance_id="avatar_led_hook",
                teaching_pattern="problem_statement",
                content_direction="Open with a relatable scenario of change resistance.",
                presentation_direction="Avatar stands in front of a neutral background.",
                target_duration_seconds=60,
            ),
            VideoSceneDraft(
                scene_id="explanation",
                source_content=(_REF,),
                learning_objective="Describe the five ADKAR stages",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="avatar_led_explanation",
                teaching_pattern="direct_instruction",
                content_direction="Walk through each ADKAR stage with brief examples.",
                presentation_direction="Avatar on solid background with text overlays.",
                target_duration_seconds=180,
            ),
        ),
    )


@pytest.fixture
def planner(tmp_path: Path) -> VideoModalityPlanner:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# System prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_two_scene_draft(), prompt_version="video_modality_v1")
    return VideoModalityPlanner(client=client, prompt_path=pp)


# ── Full pipeline ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_returns_modality_plan(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert isinstance(plan, ModalityPlan)


@pytest.mark.asyncio
async def test_e2e_correct_scene_count(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert len(plan.scenes) == 2


@pytest.mark.asyncio
async def test_e2e_plan_id_is_derived(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert plan.plan_id == "mp-e2e-adkar-draft"


@pytest.mark.asyncio
async def test_e2e_scene_affordances_are_pedagogical(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    for scene in plan.scenes:
        assert "." not in scene.preferred_capability, (
            f"Capability name leaked into preferred_capability: {scene.preferred_capability}"
        )


@pytest.mark.asyncio
async def test_e2e_presentation_direction_preserved(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert any(s.presentation_direction is not None for s in plan.scenes)


@pytest.mark.asyncio
async def test_e2e_scene_ids_are_slugged(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    for scene in plan.scenes:
        assert scene.id == scene.id.lower()
        assert " " not in scene.id


@pytest.mark.asyncio
async def test_e2e_source_content_refs_preserved(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    all_rlo_ids = {ref.rlo_id for s in plan.scenes for ref in s.source_content}
    assert "rlo-adkar-01" in all_rlo_ids


@pytest.mark.asyncio
async def test_e2e_no_heygen_ids_in_output(planner: VideoModalityPlanner) -> None:
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    dumped = plan.model_dump_json()
    assert "Annie" not in dumped
    assert "heygen" not in dumped.lower()
    assert "voice_id" not in dumped


@pytest.mark.asyncio
async def test_e2e_plan_is_json_serializable(planner: VideoModalityPlanner) -> None:
    import json
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    reloaded = ModalityPlan.model_validate_json(plan.model_dump_json())
    assert reloaded.plan_id == plan.plan_id


@pytest.mark.asyncio
async def test_e2e_deterministic_output(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# System prompt", encoding="utf-8")

    draft = _two_scene_draft()
    client1 = FakePlanningClient(draft=draft, prompt_version="video_modality_v1")
    client2 = FakePlanningClient(draft=draft, prompt_version="video_modality_v1")

    planner1 = VideoModalityPlanner(client=client1, prompt_path=pp)
    planner2 = VideoModalityPlanner(client=client2, prompt_path=pp)

    plan1 = await planner1.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    plan2 = await planner2.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)

    assert plan1.model_dump_json() == plan2.model_dump_json()
