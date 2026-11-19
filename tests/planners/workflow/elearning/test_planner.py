"""Tests for ElearningWorkflowPlanner — Phase 14D.

No live LLM, HeyGen, TTS, Manim, Docker, or network calls.

Coverage:
  1.  Returns ModalityProductionPlan.
  2.  Plan modality is ELEARNING.
  3.  Exactly one client call per plan (one-call rule).
  4.  Wrong modality raises ElearningWorkflowPlannerError.
  5.  Missing prompt file raises ElearningWorkflowPlannerError.
  6.  System prompt is passed to the planning client.
  7.  User payload contains blueprint_id from context.
  8.  User payload contains modality_plan.
  9.  User payload contains capability_constraints.
  10. User payload contains approved_profiles.
  11. Prompt file is read only once (cached).
  12. prompt_version property returns the prompt filename stem.
  13. model property returns the configured model.
  14. Invalid draft from fake client raises validation error.
  15. User payload has no provider-specific IDs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import (
    Modality,
    ModalityPlan,
    ModalityProductionPlan,
)
from learning_pipeline.contracts import LearnerContext
from learning_pipeline.contracts.planning import (
    AvatarMediaDirective,
    ElearningProductionDraft,
    ResolvedContentItem,
    ResolvedPlanningContext,
    ResolvedSceneContext,
)
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.workflow.elearning.planner import (
    ElearningWorkflowPlanner,
    ElearningWorkflowPlannerError,
)
from learning_pipeline.planners.workflow.elearning.validation import (
    ElearningDraftValidationError,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    LearnerAction,
    VideoSlotRequirement,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

_ELEARNING_PLAN_JSON = """{
  "plan_id": "mp-el-planner-test",
  "modality": "elearning",
  "narrative": "Planner test.",
  "scenes": [
    {
      "id": "scene-intro",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Understand intro.",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "elearning.static_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "intro"
    },
    {
      "id": "scene-apply",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "Apply concept.",
      "teaching_pattern": "worked_example",
      "preferred_capability": "elearning.avatar_explanation",
      "acceptable_fallbacks": [],
      "content_direction": "example"
    }
  ]
}"""

_PODCAST_PLAN_JSON = """{
  "plan_id": "mp-podcast",
  "modality": "podcast",
  "narrative": "podcast",
  "scenes": [
    {
      "id": "scene-intro",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "x",
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


def _learner() -> LearnerContext:
    return LearnerContext(
        role="Manager",
        deloitte_level=55,
        default_proficiency="beginner",
        topic_proficiencies={},
        goals=["learn"],
        duration_limit_minutes=20,
        business_context={},
    )


def _context(plan: ModalityPlan | None = None) -> ResolvedPlanningContext:
    p = plan or _elearning_plan()
    return ResolvedPlanningContext(
        blueprint_id="bp-elearning-test",
        learner=_learner(),
        scenes=tuple(
            ResolvedSceneContext(
                scene_id=s.id,
                learning_objective=s.learning_objective,
                teaching_pattern=s.teaching_pattern,
                content_items=(),
            )
            for s in p.scenes
        ),
    )


def _valid_draft() -> ElearningProductionDraft:
    return ElearningProductionDraft(
        draft_id="planner-test-draft",
        source_modality_plan_id="mp-el-planner-test",
        narrative="A test e-learning course.",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="screen-intro",
                screen_type="title",
                source_scene_ids=("scene-intro",),
                content_direction="Write the intro.",
                learner_action=LearnerAction.CONSUME,
            ),
            AuthoredScreenRequirement(
                screen_id="screen-apply",
                screen_type="concept_flip_card",
                source_scene_ids=("scene-apply",),
                content_direction="Write the application section.",
                learner_action=LearnerAction.REVEAL,
            ),
        ),
        video_slots=(),
        screen_order=("screen-intro", "screen-apply"),
        avatar_directives=(),
        manim_directives=(),
        course_authoring_direction="Use clear, professional language.",
    )


def _make_planner(
    draft: ElearningProductionDraft | None = None,
    prompt_path: Path | None = None,
    tmp_path: Path | None = None,
) -> ElearningWorkflowPlanner:
    from learning_pipeline.config import build_tool_catalog

    d = draft or _valid_draft()
    client = FakePlanningClient(draft=d, prompt_version="elearning_v1")
    catalog = build_tool_catalog()

    if prompt_path is None:
        pp = (tmp_path or Path("/tmp")) / "elearning_v1.md"
        pp.write_text("# E-learning test prompt", encoding="utf-8")
        prompt_path = pp

    return ElearningWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=prompt_path,
    )


# ── 1: Returns ModalityProductionPlan ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_returns_modality_production_plan(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _elearning_plan())
    assert isinstance(plan, ModalityProductionPlan)


# ── 2: Plan modality is ELEARNING ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_modality_is_elearning(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _elearning_plan())
    assert plan.modality == Modality.ELEARNING


# ── 3: Exactly one client call ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exactly_one_client_call(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    planner = ElearningWorkflowPlanner(
        client=client,
        catalog=build_tool_catalog(),
        prompt_path=pp,
    )
    assert client.call_count == 0
    await planner.plan(_context(), _elearning_plan())
    assert client.call_count == 1


# ── 4: Wrong modality raises ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_modality_raises(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    with pytest.raises(ElearningWorkflowPlannerError, match="elearning"):
        await planner.plan(_context(_podcast_plan()), _podcast_plan())


# ── 5: Missing prompt file raises ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_prompt_file_raises(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client,
        catalog=build_tool_catalog(),
        prompt_path=tmp_path / "nonexistent.md",
    )
    with pytest.raises(ElearningWorkflowPlannerError, match="Cannot load"):
        await planner.plan(_context(), _elearning_plan())


# ── 6: System prompt is passed to client ─────────────────────────────────────

@pytest.mark.asyncio
async def test_system_prompt_passed_to_client(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    prompt_text = "# My elearning system prompt"
    pp = tmp_path / "elearning_v1.md"
    pp.write_text(prompt_text, encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client,
        catalog=build_tool_catalog(),
        prompt_path=pp,
    )
    await planner.plan(_context(), _elearning_plan())
    assert client.last_system_prompt == prompt_text


# ── 7: User payload contains blueprint_id ─────────────────────────────────────

@pytest.mark.asyncio
async def test_user_payload_contains_blueprint_id(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    ctx = _context()
    await planner.plan(ctx, _elearning_plan())
    from learning_pipeline.config import build_tool_catalog
    # Re-run to inspect payload via direct client access
    from learning_pipeline.planners.client import FakePlanningClient as FPC
    client = FPC(draft=_valid_draft(), prompt_version="elearning_v1")
    pp = tmp_path / "ep.md"
    pp.write_text("# prompt", encoding="utf-8")
    p2 = ElearningWorkflowPlanner(client=client, catalog=build_tool_catalog(), prompt_path=pp)
    await p2.plan(ctx, _elearning_plan())
    assert client.last_user_payload["blueprint_id"] == "bp-elearning-test"


# ── 8: User payload contains modality_plan ────────────────────────────────────

@pytest.mark.asyncio
async def test_user_payload_contains_modality_plan(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )
    await planner.plan(_context(), _elearning_plan())
    assert "modality_plan" in client.last_user_payload


# ── 9: User payload contains capability_constraints ───────────────────────────

@pytest.mark.asyncio
async def test_user_payload_contains_capability_constraints(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )
    await planner.plan(_context(), _elearning_plan())
    constraints = client.last_user_payload.get("capability_constraints", {})
    assert "elearning.course.author" in constraints


# ── 10: User payload contains approved_profiles ───────────────────────────────

@pytest.mark.asyncio
async def test_user_payload_contains_approved_profiles(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )
    await planner.plan(_context(), _elearning_plan())
    profiles = client.last_user_payload.get("approved_profiles", {})
    assert "avatar_profiles" in profiles
    assert "voice_profiles" in profiles


@pytest.mark.asyncio
async def test_user_payload_has_no_numeric_course_screen_budget(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )

    await planner.plan(_context(), _elearning_plan())

    assert "course_screen_budget" not in client.last_user_payload


@pytest.mark.asyncio
async def test_many_required_assessments_are_not_rejected_by_a_screen_cap(
    tmp_path: Path,
) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    context = _context()
    assessment_items = tuple(
        ResolvedContentItem(
            rlo_id="rlo-generic",
            rlo_version="1",
            content_type="assessment_item",
            content_id=f"question-{index}",
            content="Approved multiple-choice question.",
        )
        for index in range(20)
    )
    context = context.model_copy(
        update={
            "scenes": (
                context.scenes[0],
                context.scenes[1].model_copy(update={"content_items": assessment_items}),
            )
        }
    )
    draft = _valid_draft().model_copy(
        update={
            "authored_screens": (
                _valid_draft().authored_screens[0],
                AuthoredScreenRequirement(
                    screen_id="screen-check",
                    screen_type="knowledge_check",
                    source_scene_ids=("scene-apply",),
                    content_direction="Render every approved assessment item.",
                    learner_action=LearnerAction.CHOOSE,
                ),
            ),
            "screen_order": ("screen-intro", "screen-check"),
        }
    )
    client = FakePlanningClient(draft=draft, prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )

    result = await planner.plan(context, _elearning_plan())

    assert isinstance(result, ModalityProductionPlan)
    assert client.call_count == 1


# ── 11: Prompt file read only once ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prompt_file_read_only_once(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )
    await planner.plan(_context(), _elearning_plan())
    pp.unlink()
    # Second call uses cached prompt
    await planner.plan(_context(), _elearning_plan())
    assert client.call_count == 2


# ── 12: prompt_version property ───────────────────────────────────────────────

def test_prompt_version_property(tmp_path: Path) -> None:
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    planner = _make_planner(prompt_path=pp)
    assert planner.prompt_version == "elearning_v1"


# ── 13: model property ────────────────────────────────────────────────────────

def test_model_property(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client,
        catalog=build_tool_catalog(),
        prompt_path=pp,
        model="custom-elearning-model",
    )
    assert planner.model == "custom-elearning-model"


# ── 14: Invalid draft raises validation error ─────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_draft_raises_validation_error(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    bad_draft = ElearningProductionDraft(
        draft_id="bad-draft",
        source_modality_plan_id="wrong-plan-id",  # mismatch
        narrative="test",
        authored_screens=(
            AuthoredScreenRequirement(
                screen_id="s1",
                screen_type="title",
                source_scene_ids=("scene-intro",),
                content_direction="intro",
                learner_action=LearnerAction.CONSUME,
            ),
            AuthoredScreenRequirement(
                screen_id="s2",
                screen_type="key_takeaways",
                source_scene_ids=("scene-apply",),
                content_direction="apply",
                learner_action=LearnerAction.CONSUME,
            ),
        ),
        video_slots=(),
        screen_order=("s1", "s2"),
        avatar_directives=(),
        manim_directives=(),
        course_authoring_direction="direction",
    )
    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=bad_draft, prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )
    with pytest.raises(ElearningDraftValidationError, match="source_modality_plan_id"):
        await planner.plan(_context(), _elearning_plan())


# ── 15: User payload has no provider-specific IDs ─────────────────────────────

@pytest.mark.asyncio
async def test_user_payload_has_no_provider_ids(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog
    import json

    pp = tmp_path / "elearning_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="elearning_v1")
    planner = ElearningWorkflowPlanner(
        client=client, catalog=build_tool_catalog(), prompt_path=pp
    )
    await planner.plan(_context(), _elearning_plan())
    payload_str = json.dumps(client.last_user_payload)
    assert "Annie_expressive_public" not in payload_str
    assert "HEYGEN_API_KEY" not in payload_str
    assert "api_key" not in payload_str.lower() or "api_key" not in payload_str
