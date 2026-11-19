"""Tests for PodcastWorkflowPlanner — Phase 9."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_pipeline.contracts import Modality, ModalityPlan, ModalityProductionPlan
from learning_pipeline.contracts.planning import (
    PodcastProductionDraft,
    PodcastSpeechSegmentDraft,
)
from learning_pipeline.planners.client import FakePlanningClient, PlanningOutputValidationError
from learning_pipeline.planners.context import PlanningContextResolver
from learning_pipeline.planners.workflow.podcast.planner import (
    PROMPT_VERSION,
    PodcastPlannerError,
    PodcastWorkflowPlanner,
)
from learning_pipeline.contracts.planning import (
    ResolvedContentItem,
    ResolvedPlanningContext,
    ResolvedSceneContext,
)
from learning_pipeline.contracts import LearnerContext

_MODALITY_PLAN_JSON = """{
  "plan_id": "mp-test",
  "modality": "podcast",
  "narrative": "test",
  "scenes": [
    {
      "id": "scene-a",
      "source_content": [
        {"rlo_id": "rlo-test", "rlo_version": "1.0.0", "objective_ids": ["lo-01"]}
      ],
      "learning_objective": "obj",
      "teaching_pattern": "hook_then_rule",
      "preferred_capability": "narration",
      "acceptable_fallbacks": [],
      "content_direction": "Introduce the concept."
    },
    {
      "id": "scene-b",
      "source_content": [
        {"rlo_id": "rlo-test", "rlo_version": "1.0.0", "objective_ids": ["lo-01"]}
      ],
      "learning_objective": "obj2",
      "teaching_pattern": "example_nonexample",
      "preferred_capability": "narration",
      "acceptable_fallbacks": [],
      "content_direction": "Provide examples."
    }
  ]
}"""

_VIDEO_PLAN_JSON = """{
  "plan_id": "mp-video",
  "modality": "video",
  "narrative": "video plan",
  "scenes": [
    {
      "id": "scene-v1",
      "source_content": [
        {"rlo_id": "rlo-test", "rlo_version": "1.0.0", "objective_ids": ["lo-01"]}
      ],
      "learning_objective": "video obj",
      "teaching_pattern": "demonstration",
      "preferred_capability": "video",
      "acceptable_fallbacks": [],
      "content_direction": "Show the process."
    }
  ]
}"""


def _modality_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_MODALITY_PLAN_JSON)


def _video_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_VIDEO_PLAN_JSON)


def _learner() -> LearnerContext:
    return LearnerContext(
        role="Manager",
        deloitte_level=55,
        default_proficiency="beginner",
        topic_proficiencies={},
        goals=["test goal"],
        duration_limit_minutes=10,
        business_context={},
    )


def _context(plan: ModalityPlan | None = None) -> ResolvedPlanningContext:
    p = plan or _modality_plan()
    return ResolvedPlanningContext(
        blueprint_id="bp-test",
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


def _valid_draft(plan: ModalityPlan | None = None) -> PodcastProductionDraft:
    p = plan or _modality_plan()
    scene_ids = [s.id for s in p.scenes]
    return PodcastProductionDraft(
        draft_id="test-draft",
        title="Test Episode",
        narrative_summary="A test episode.",
        segments=tuple(
            PodcastSpeechSegmentDraft(
                segment_id=f"seg-{i + 1:02d}",
                source_scene_ids=(sid,),
                speaker="Host" if i % 2 == 0 else "Expert",
                text="Hello world.",
                learning_purpose="test",
            )
            for i, sid in enumerate(scene_ids)
        ),
    )


def _make_planner(
    draft: PodcastProductionDraft | None = None,
    prompt_path: Path | None = None,
    tmp_path: Path | None = None,
) -> PodcastWorkflowPlanner:
    from learning_pipeline.config import build_tool_catalog

    d = draft or _valid_draft()
    client = FakePlanningClient(draft=d)
    catalog = build_tool_catalog()

    if prompt_path is None:
        # Create a minimal valid prompt file
        pp = (tmp_path or Path("/tmp")) / "podcast_v1.md"
        pp.write_text("# Test system prompt", encoding="utf-8")
        prompt_path = pp

    return PodcastWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=prompt_path,
    )


def test_prompt_version_invalidates_prior_cached_plans(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    assert PROMPT_VERSION == "podcast_v7"
    assert planner.prompt_version == "podcast_v7"


def test_default_prompt_defines_genuine_host_expert_dialogue() -> None:
    from learning_pipeline.planners.workflow.podcast.planner import _DEFAULT_PROMPT_PATH

    prompt = _DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
    assert "The Host must not teach" in prompt
    assert "The Expert must not" in prompt
    assert "topic-relevant professional background" in prompt
    assert "Expert question → Host response → Expert feedback" in prompt
    assert "No assessment creates a silent listener-response window" in prompt
    assert "150 words per minute" in prompt
    assert "quality target" in prompt


# ── Basic planning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_modality_production_plan(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _modality_plan())
    assert isinstance(plan, ModalityProductionPlan)


@pytest.mark.asyncio
async def test_plan_modality_is_podcast(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _modality_plan())
    assert plan.modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_plan_has_speech_and_assembly_jobs(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _modality_plan())
    capabilities = {j.capability for j in plan.jobs}
    assert "speech.synthesize" in capabilities
    assert "audio.assemble" in capabilities


# ── One-call rule ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exactly_one_client_call_per_plan(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    client = FakePlanningClient(draft=_valid_draft())
    catalog = build_tool_catalog()
    pp = tmp_path / "podcast_v1.md"
    pp.write_text("# Test prompt", encoding="utf-8")
    planner = PodcastWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    assert client.call_count == 0
    await planner.plan(_context(), _modality_plan())
    assert client.call_count == 1


# ── Wrong modality ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_modality_raises(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    with pytest.raises(PodcastPlannerError, match="podcast"):
        await planner.plan(_context(_video_plan()), _video_plan())


# ── Missing prompt file ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_prompt_file_raises(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    client = FakePlanningClient(draft=_valid_draft())
    catalog = build_tool_catalog()
    planner = PodcastWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=tmp_path / "nonexistent.md",
    )
    with pytest.raises(PodcastPlannerError, match="Cannot load"):
        await planner.plan(_context(), _modality_plan())


# ── System prompt is passed to client ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_prompt_passed_to_client(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    prompt_text = "# My custom system prompt"
    pp = tmp_path / "podcast_v1.md"
    pp.write_text(prompt_text, encoding="utf-8")

    client = FakePlanningClient(draft=_valid_draft())
    catalog = build_tool_catalog()
    planner = PodcastWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _modality_plan())
    assert client.last_system_prompt == prompt_text


# ── User payload contains context data ────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_payload_contains_blueprint_id(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "podcast_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft())
    catalog = build_tool_catalog()
    planner = PodcastWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    ctx = _context()
    await planner.plan(ctx, _modality_plan())
    assert client.last_user_payload is not None
    assert client.last_user_payload.get("blueprint_id") == ctx.blueprint_id


# ── Draft caching ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_file_read_once(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "podcast_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft())
    catalog = build_tool_catalog()
    planner = PodcastWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _modality_plan())
    # Delete the file — second call should use cached prompt
    pp.unlink()
    await planner.plan(_context(), _modality_plan())
    assert client.call_count == 2
