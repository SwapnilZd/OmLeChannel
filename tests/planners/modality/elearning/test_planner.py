"""ElearningModalityPlanner tests — Phase 14E.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  10. Valid structured e-learning modality draft passes.
  11. Modality must be ELEARNING.
  12. Empty scene plan rejected (Pydantic min_length).
  13. Duplicate scene IDs rejected (model_validator).
  14. Unknown affordance rejected.
  16. Tool names in affordance fields rejected.
  18. Excluded source content rejected.
  19. RLO version mismatch rejected.
  27. Scene lineage survives serialization.
  29. Valid output requires one model call.
  30. Invalid structured output raises on validation failure.
  31. No production tool is called by the Modality Planner.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    ElearningModalityDraft,
    ElearningSceneDraft,
    ModalityPlanningContext,
    NarrativeRole,
    ResolvedRLOContext,
)
from learning_pipeline.affordances.catalog import ModalityAffordanceCatalog, PlannerAffordanceView
from learning_pipeline.affordances.elearning import build_elearning_affordance_catalog
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.modality.elearning.planner import (
    PROMPT_VERSION,
    ElearningModalityPlanner,
    ElearningModalityPlannerError,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-el-planner-test",
  "title": "E-learning Planner Test",
  "learner": {
    "role": "Analyst", "deloitte_level": 45, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["understand the topic"], "business_context": {}
  },
  "learning_outcomes": [],
  "ordered_rlo_refs": [
    {
      "rlo_id": "rlo-1", "rlo_version": "1.0", "order": 1,
      "selected_content": {
        "objective_ids": ["obj-1"],
        "concept_ids": ["con-1"],
        "component_ids": [],
        "assessment_item_ids": []
      },
      "starting_proficiency": "beginner", "target_proficiency": "intermediate",
      "content_depth": "working", "role_relevance": "core",
      "personalization_rationale": "test", "sequencing_rationale": "test",
      "adaptation_instructions": []
    }
  ],
  "prerequisite_bridges": [], "brand_contract": {},
  "sequencing_rationale": "test", "assessment_strategy": "formative",
  "estimated_duration_minutes": 10, "source_rlo_versions": {"rlo-1": "1.0"}
}"""

_BLUEPRINT = CourseBlueprint.model_validate_json(_BLUEPRINT_JSON)

_RLO_CTX = ResolvedRLOContext(
    rlo_id="rlo-1", rlo_version="1.0", order=1, title="Test RLO", topic="test",
    terminal_objective_text="Understand the test concept",
    enabling_objectives=(), concepts=(), components=(), assessment_items=(),
    selected_objective_ids=("obj-1",), selected_concept_ids=("con-1",),
    selected_component_ids=(), selected_assessment_ids=(),
    role_relevance="core", example_context=None, adaptation_instructions=(),
)

_CONTEXT = ModalityPlanningContext(
    blueprint_id="bp-el-planner-test",
    learner=_BLUEPRINT.learner,
    rlo_contexts=(_RLO_CTX,),
)

_CATALOG = build_elearning_affordance_catalog()
_AFFORDANCE_VIEW = PlannerAffordanceView(
    modality=Modality.ELEARNING,
    affordances=_CATALOG.affordances_for(Modality.ELEARNING),
)

_REF = RLOContentRef(
    rlo_id="rlo-1", rlo_version="1.0",
    objective_ids=("obj-1",), concept_ids=("con-1",),
)


def _valid_draft() -> ElearningModalityDraft:
    return ElearningModalityDraft(
        draft_id="el-planner-test-draft",
        title="E-learning Planner Test",
        narrative="A test e-learning modality plan.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-intro",
                source_content=(_REF,),
                learning_objective="Understand the test concept",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction",
                content_direction="Explain the concept clearly with examples.",
                target_duration_seconds=60,
            ),
        ),
    )


def _make_planner(
    draft: ElearningModalityDraft | None = None,
    prompt_path: Path | None = None,
    tmp: Path | None = None,
) -> ElearningModalityPlanner:
    d = draft or _valid_draft()
    client = FakePlanningClient(draft=d, prompt_version=PROMPT_VERSION)
    if prompt_path is None:
        pp = (tmp or Path("/tmp")) / "elearning_v1.md"
        pp.write_text("# Test E-learning Prompt", encoding="utf-8")
        prompt_path = pp
    return ElearningModalityPlanner(client=client, prompt_path=prompt_path)


# ── 10: Valid draft passes ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_modality_plan(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    assert isinstance(plan, ModalityPlan)


@pytest.mark.asyncio
async def test_plan_modality_is_elearning(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    assert plan.modality == Modality.ELEARNING


@pytest.mark.asyncio
async def test_plan_has_scenes(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    assert len(plan.scenes) >= 1


# ── 11: Wrong modality raises ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_modality_raises(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="elearning"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.PODCAST, _CONTEXT, _AFFORDANCE_VIEW)


@pytest.mark.asyncio
async def test_video_modality_raises(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="elearning"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)


# ── 12: Empty scene plan rejected ─────────────────────────────────────────────


def test_empty_scenes_rejected_by_pydantic() -> None:
    with pytest.raises(Exception):
        ElearningModalityDraft(
            draft_id="bad", title="Bad", narrative="Bad.",
            scenes=(),
        )


# ── 13: Duplicate scene IDs rejected ─────────────────────────────────────────


def test_duplicate_scene_ids_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        ElearningModalityDraft(
            draft_id="bad", title="Bad", narrative="Bad.",
            scenes=(
                ElearningSceneDraft(
                    scene_id="scene-a",
                    source_content=(_REF,),
                    learning_objective="obj",
                    narrative_role=NarrativeRole.EXPLANATION,
                    affordance_id="elearning.static_explanation",
                    teaching_pattern="direct_instruction",
                    content_direction="dir",
                    target_duration_seconds=60,
                ),
                ElearningSceneDraft(
                    scene_id="scene-a",  # duplicate
                    source_content=(_REF,),
                    learning_objective="obj2",
                    narrative_role=NarrativeRole.SUMMARY,
                    affordance_id="elearning.summary",
                    teaching_pattern="summarization",
                    content_direction="dir2",
                    target_duration_seconds=60,
                ),
            ),
        )


# ── 14: Unknown affordance rejected ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_affordance_raises(tmp_path: Path) -> None:
    bad_draft = ElearningModalityDraft(
        draft_id="bad",
        title="Bad",
        narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-a",
                source_content=(_REF,),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="unknown.affordance",
                teaching_pattern="direct_instruction",
                content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    planner = _make_planner(draft=bad_draft, tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)


# ── 16: Tool names in affordance fields rejected ──────────────────────────────


@pytest.mark.asyncio
async def test_tool_name_as_affordance_id_raises(tmp_path: Path) -> None:
    bad_draft = ElearningModalityDraft(
        draft_id="bad",
        title="Bad",
        narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-a",
                source_content=(_REF,),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.course.author",  # 3-segment capability name
                teaching_pattern="direct_instruction",
                content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    planner = _make_planner(draft=bad_draft, tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)


@pytest.mark.asyncio
async def test_manim_capability_as_affordance_raises(tmp_path: Path) -> None:
    bad_draft = ElearningModalityDraft(
        draft_id="bad",
        title="Bad",
        narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-a",
                source_content=(_REF,),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="video.manim.render",  # capability ID
                teaching_pattern="direct_instruction",
                content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    planner = _make_planner(draft=bad_draft, tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)


# ── 18: Excluded source content rejected ──────────────────────────────────────


@pytest.mark.asyncio
async def test_unselected_concept_raises(tmp_path: Path) -> None:
    bad_ref = RLOContentRef(
        rlo_id="rlo-1", rlo_version="1.0",
        concept_ids=("con-EXCLUDED",),  # not in selected_concept_ids
    )
    bad_draft = ElearningModalityDraft(
        draft_id="bad",
        title="Bad",
        narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-a",
                source_content=(bad_ref,),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction",
                content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    planner = _make_planner(draft=bad_draft, tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)


# ── 19: RLO version mismatch rejected ────────────────────────────────────────


@pytest.mark.asyncio
async def test_rlo_version_mismatch_raises(tmp_path: Path) -> None:
    bad_ref = RLOContentRef(
        rlo_id="rlo-1", rlo_version="9.9",  # wrong version
        objective_ids=("obj-1",),
    )
    bad_draft = ElearningModalityDraft(
        draft_id="bad",
        title="Bad",
        narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-a",
                source_content=(bad_ref,),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction",
                content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    planner = _make_planner(draft=bad_draft, tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)


# ── 27: Scene lineage survives serialization ──────────────────────────────────


@pytest.mark.asyncio
async def test_scene_source_content_preserved(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    scene = plan.scenes[0]
    ref = scene.source_content[0]
    assert ref.rlo_id == "rlo-1"
    assert ref.rlo_version == "1.0"
    assert "obj-1" in ref.objective_ids


@pytest.mark.asyncio
async def test_plan_survives_json_round_trip(tmp_path: Path) -> None:
    from learning_pipeline.contracts.modality import ModalityPlan
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    restored = ModalityPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan


# ── 29: Valid output requires one model call ──────────────────────────────────


@pytest.mark.asyncio
async def test_exactly_one_client_call(tmp_path: Path) -> None:
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)

    assert client.call_count == 0
    await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    assert client.call_count == 1


# ── 30: Invalid structured output raises (validation failure) ─────────────────


@pytest.mark.asyncio
async def test_invalid_draft_raises_on_validation(tmp_path: Path) -> None:
    # A draft that references a non-existent RLO
    bad_ref = RLOContentRef(rlo_id="rlo-DOES-NOT-EXIST", rlo_version="1.0")
    bad_draft = ElearningModalityDraft(
        draft_id="bad", title="Bad", narrative="Bad.",
        scenes=(
            ElearningSceneDraft(
                scene_id="scene-a",
                source_content=(bad_ref,),
                learning_objective="obj",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="elearning.static_explanation",
                teaching_pattern="direct_instruction",
                content_direction="dir",
                target_duration_seconds=60,
            ),
        ),
    )
    planner = _make_planner(draft=bad_draft, tmp=tmp_path)
    with pytest.raises(ElearningModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)


# ── 31: No production tool is called ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_production_tool_called(tmp_path: Path) -> None:
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    # Only one client call; no executor/registry involved
    assert client.call_count == 1
    assert isinstance(plan, ModalityPlan)


# ── Public properties ─────────────────────────────────────────────────────────


def test_prompt_version_property(tmp_path: Path) -> None:
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    planner = _make_planner(prompt_path=pp)
    assert planner.prompt_version == PROMPT_VERSION


def test_model_property(tmp_path: Path) -> None:
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    planner = ElearningModalityPlanner(client=client, prompt_path=pp, model="custom-model")
    assert planner.model == "custom-model"


def test_missing_prompt_raises(tmp_path: Path) -> None:
    import asyncio
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    planner = ElearningModalityPlanner(client=client, prompt_path=tmp_path / "nonexistent.md")

    with pytest.raises(ElearningModalityPlannerError, match="Cannot load"):
        asyncio.run(
            planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
        )


def test_system_prompt_passed_to_client(tmp_path: Path) -> None:
    import asyncio
    prompt_text = "# My e-learning modality prompt"
    pp = tmp_path / "elearning_v1.md"
    pp.write_text(prompt_text, encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)

    asyncio.run(
        planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    )
    assert client.last_system_prompt == prompt_text


def test_user_payload_contains_affordances(tmp_path: Path) -> None:
    import asyncio
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)

    asyncio.run(
        planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    )
    assert "affordances" in client.last_user_payload


def test_user_payload_no_provider_ids(tmp_path: Path) -> None:
    import asyncio, json
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)

    asyncio.run(
        planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    )
    payload_str = json.dumps(client.last_user_payload)
    assert "Annie_expressive_public" not in payload_str
    assert "HEYGEN_API_KEY" not in payload_str
    assert "LITE_LLM_API_KEY" not in payload_str


def test_prompt_cached_after_first_read(tmp_path: Path) -> None:
    import asyncio
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version=PROMPT_VERSION)
    planner = ElearningModalityPlanner(client=client, prompt_path=pp)
    asyncio.run(
        planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    )
    pp.unlink()
    asyncio.run(
        planner.create_modality_plan(_BLUEPRINT, Modality.ELEARNING, _CONTEXT, _AFFORDANCE_VIEW)
    )
    assert client.call_count == 2
