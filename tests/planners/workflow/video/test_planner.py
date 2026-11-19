"""Tests for VideoWorkflowPlanner — Phase 13B."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import Modality, ModalityPlan, ModalityProductionPlan
from learning_pipeline.contracts.planning import (
    AvatarVideoSceneDraft,
    VideoBackgroundDraft,
    ResolvedPlanningContext,
    ResolvedSceneContext,
    VideoProductionDraft,
)
from learning_pipeline.contracts import LearnerContext
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.workflow.video.planner import (
    VideoWorkflowPlanner,
    VideoWorkflowPlannerError,
)

_VIDEO_PLAN_JSON = """{
  "plan_id": "mp-test-video",
  "modality": "video",
  "narrative": "test",
  "scenes": [
    {
      "id": "scene-a",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "obj-a",
      "teaching_pattern": "hook_then_rule",
      "preferred_capability": "avatar_video",
      "acceptable_fallbacks": [],
      "content_direction": "open with a hook"
    },
    {
      "id": "scene-b",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "obj-b",
      "teaching_pattern": "direct_instruction",
      "preferred_capability": "avatar_video",
      "acceptable_fallbacks": [],
      "content_direction": "explain the concepts"
    }
  ]
}"""

_PODCAST_PLAN_JSON = """{
  "plan_id": "mp-test-podcast",
  "modality": "podcast",
  "narrative": "test",
  "scenes": [
    {
      "id": "scene-a",
      "source_content": [{"rlo_id": "rlo-1", "rlo_version": "1.0"}],
      "learning_objective": "obj",
      "teaching_pattern": "hook_then_rule",
      "preferred_capability": "narration",
      "acceptable_fallbacks": [],
      "content_direction": "intro"
    }
  ]
}"""


def _video_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_VIDEO_PLAN_JSON)


def _podcast_plan() -> ModalityPlan:
    return ModalityPlan.model_validate_json(_PODCAST_PLAN_JSON)


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
    p = plan or _video_plan()
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


def _valid_draft(plan: ModalityPlan | None = None) -> VideoProductionDraft:
    p = plan or _video_plan()
    return VideoProductionDraft(
        draft_id="test-video-draft",
        title="Test Video",
        narrative_summary="A test video.",
        render_capability="video.avatar.render",
        avatar_profile="default_instructor",
        voice_profile="default_instructor",
        width=1280,
        height=720,
        captions=False,
        scenes=tuple(
            AvatarVideoSceneDraft(
                scene_id=s.id,
                source_scene_ids=(s.id,),
                script=f"Narration for {s.id}.",
                background=VideoBackgroundDraft(kind="color", color="#1A1A2E"),
                estimated_duration_seconds=60.0,
            )
            for s in p.scenes
        ),
        production_rationale="test",
    )


def _make_planner(
    draft: VideoProductionDraft | None = None,
    prompt_path: Path | None = None,
    tmp_path: Path | None = None,
) -> VideoWorkflowPlanner:
    from learning_pipeline.config import build_tool_catalog

    d = draft or _valid_draft()
    client = FakePlanningClient(draft=d, prompt_version="video_v1")
    catalog = build_tool_catalog()

    if prompt_path is None:
        pp = (tmp_path or Path("/tmp")) / "video_v1.md"
        pp.write_text("# Test video prompt", encoding="utf-8")
        prompt_path = pp

    return VideoWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=prompt_path,
    )


# ── Basic planning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_modality_production_plan(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _video_plan())
    assert isinstance(plan, ModalityProductionPlan)


@pytest.mark.asyncio
async def test_plan_modality_is_video(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _video_plan())
    assert plan.modality == Modality.VIDEO


@pytest.mark.asyncio
async def test_plan_has_render_job(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    plan = await planner.plan(_context(), _video_plan())
    assert len(plan.jobs) == 1
    assert plan.jobs[0].capability == "video.avatar.render"


# ── One-call rule ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exactly_one_client_call_per_plan(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    pp = tmp_path / "video_v1.md"
    pp.write_text("# Test prompt", encoding="utf-8")
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    assert client.call_count == 0
    await planner.plan(_context(), _video_plan())
    assert client.call_count == 1


# ── Wrong modality ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_modality_raises(tmp_path: Path) -> None:
    planner = _make_planner(tmp_path=tmp_path)
    with pytest.raises(VideoWorkflowPlannerError, match="video"):
        await planner.plan(_context(_podcast_plan()), _podcast_plan())


# ── Missing prompt file ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_prompt_file_raises(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=tmp_path / "nonexistent.md",
    )
    with pytest.raises(VideoWorkflowPlannerError, match="Cannot load"):
        await planner.plan(_context(), _video_plan())


# ── System prompt is passed to client ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_prompt_passed_to_client(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    prompt_text = "# My video system prompt"
    pp = tmp_path / "video_v1.md"
    pp.write_text(prompt_text, encoding="utf-8")

    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _video_plan())
    assert client.last_system_prompt == prompt_text


# ── User payload contains context + modality plan ─────────────────────────────


@pytest.mark.asyncio
async def test_user_payload_contains_blueprint_id(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    ctx = _context()
    await planner.plan(ctx, _video_plan())
    assert client.last_user_payload is not None
    assert client.last_user_payload.get("blueprint_id") == ctx.blueprint_id


@pytest.mark.asyncio
async def test_user_payload_contains_modality_plan(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _video_plan())
    assert "modality_plan" in client.last_user_payload


@pytest.mark.asyncio
async def test_user_payload_contains_capability_constraints(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _video_plan())
    constraints = client.last_user_payload.get("capability_constraints", {})
    assert constraints.get("render_capability") == "video.avatar.render"


@pytest.mark.asyncio
async def test_user_payload_contains_approved_profiles(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _video_plan())
    profiles = client.last_user_payload.get("approved_profiles", {})
    assert "avatar_profiles" in profiles
    assert "voice_profiles" in profiles


# ── Provider IDs absent from user payload ─────────────────────────────────────


@pytest.mark.asyncio
async def test_user_payload_has_no_provider_ids(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _video_plan())
    import json
    payload_str = json.dumps(client.last_user_payload)
    assert "Annie_expressive_public" not in payload_str
    assert "330290724a1b470fb63153f34d4c0183" not in payload_str
    assert "HEYGEN_API_KEY" not in payload_str


# ── Prompt caching ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_file_read_once(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp)

    await planner.plan(_context(), _video_plan())
    pp.unlink()
    # Second call should use cached prompt without re-reading the file
    await planner.plan(_context(), _video_plan())
    assert client.call_count == 2


# ── Public properties ─────────────────────────────────────────────────────────


def test_prompt_version_property(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    planner = _make_planner(prompt_path=pp)
    assert planner.prompt_version == "video_v1"


def test_model_property(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog

    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(client=client, catalog=catalog, prompt_path=pp, model="custom-model")
    assert planner.model == "custom-model"


# ── Profile validation propagated ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_avatar_profile_in_draft_fails(tmp_path: Path) -> None:
    from learning_pipeline.config import build_tool_catalog
    from learning_pipeline.planners.workflow.video.validation import VideoDraftValidationError

    bad_draft = VideoProductionDraft(
        **{**_valid_draft().model_dump(), "avatar_profile": "unknown_profile"},
    )
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=bad_draft, prompt_version="video_v1")
    catalog = build_tool_catalog()
    planner = VideoWorkflowPlanner(
        client=client,
        catalog=catalog,
        prompt_path=pp,
        approved_avatar_profiles=frozenset({"default_instructor"}),
    )
    with pytest.raises(VideoDraftValidationError, match="avatar_profile"):
        await planner.plan(_context(), _video_plan())
