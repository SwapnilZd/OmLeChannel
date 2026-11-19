"""VideoModalityPlanner tests — Phase 13C."""
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
from learning_pipeline.planners.modality.video.planner import (
    PROMPT_VERSION,
    VideoModalityPlanner,
    VideoModalityPlannerError,
)

_BLUEPRINT_JSON = """{
  "blueprint_id": "bp-planner-test",
  "title": "Planner Test",
  "learner": {
    "role": "Manager", "deloitte_level": 55, "default_proficiency": "beginner",
    "topic_proficiencies": {}, "goals": ["test"], "business_context": {}
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

_RLO_CTX = ResolvedRLOContext(
    rlo_id="rlo-1", rlo_version="1.0", order=1, title="Test RLO", topic="test",
    terminal_objective_text="test objective",
    enabling_objectives=(), concepts=(), components=(), assessment_items=(),
    selected_objective_ids=("obj-1",), selected_concept_ids=("con-1",),
    selected_component_ids=(), selected_assessment_ids=(),
    role_relevance="test", example_context=None, adaptation_instructions=(),
)

_CONTEXT = ModalityPlanningContext(
    blueprint_id="bp-planner-test",
    learner=_BLUEPRINT.learner,
    rlo_contexts=(_RLO_CTX,),
)

_CATALOG = ModalityAffordanceCatalog(VIDEO_AFFORDANCES)
_AFFORDANCE_VIEW = PlannerAffordanceView(
    modality=Modality.VIDEO,
    affordances=_CATALOG.affordances_for(Modality.VIDEO),
)

_REF = RLOContentRef(rlo_id="rlo-1", rlo_version="1.0", objective_ids=("obj-1",), concept_ids=("con-1",))


def _valid_draft() -> VideoModalityDraft:
    return VideoModalityDraft(
        draft_id="planner-test-draft",
        title="Planner Test Video",
        narrative="A test narrative.",
        scenes=(
            VideoSceneDraft(
                scene_id="scene-a",
                source_content=(_REF,),
                learning_objective="Understand X",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="avatar_led_explanation",
                teaching_pattern="direct_instruction",
                content_direction="Explain X clearly.",
                presentation_direction="Avatar on solid background.",
                target_duration_seconds=60,
            ),
        ),
    )


def _make_planner(
    draft: VideoModalityDraft | None = None,
    prompt_path: Path | None = None,
    tmp: Path | None = None,
) -> VideoModalityPlanner:
    d = draft or _valid_draft()
    client = FakePlanningClient(draft=d, prompt_version="video_modality_v1")
    if prompt_path is None:
        pp = (tmp or Path("/tmp")) / "video_v1.md"
        pp.write_text("# Test", encoding="utf-8")
        prompt_path = pp
    return VideoModalityPlanner(client=client, prompt_path=prompt_path)


# ── Basic planning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_modality_plan(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert isinstance(plan, ModalityPlan)


@pytest.mark.asyncio
async def test_plan_modality_is_video(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert plan.modality == Modality.VIDEO


@pytest.mark.asyncio
async def test_plan_has_scenes(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    plan = await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert len(plan.scenes) >= 1


# ── One-call rule ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exactly_one_client_call(tmp_path: Path) -> None:
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    pp = tmp_path / "video_v1.md"
    pp.write_text("# Test", encoding="utf-8")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)

    assert client.call_count == 0
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert client.call_count == 1


# ── Wrong modality ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_modality_raises(tmp_path: Path) -> None:
    planner = _make_planner(tmp=tmp_path)
    with pytest.raises(VideoModalityPlannerError, match="video"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.PODCAST, _CONTEXT, _AFFORDANCE_VIEW)


# ── Missing prompt ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_prompt_raises(tmp_path: Path) -> None:
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=tmp_path / "nonexistent.md")
    with pytest.raises(VideoModalityPlannerError, match="Cannot load"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)


# ── System prompt passed to client ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_prompt_passed_to_client(tmp_path: Path) -> None:
    prompt_text = "# My video modality prompt"
    pp = tmp_path / "video_v1.md"
    pp.write_text(prompt_text, encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)

    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert client.last_system_prompt == prompt_text


# ── User payload ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_payload_contains_blueprint_id(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert client.last_user_payload.get("blueprint_id") == "bp-planner-test"


@pytest.mark.asyncio
async def test_user_payload_contains_affordances(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert "affordances" in client.last_user_payload


@pytest.mark.asyncio
async def test_user_payload_no_provider_ids(tmp_path: Path) -> None:
    import json
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    payload_str = json.dumps(client.last_user_payload)
    assert "Annie_expressive_public" not in payload_str
    assert "330290724a1b470fb63153f34d4c0183" not in payload_str
    assert "HEYGEN_API_KEY" not in payload_str


@pytest.mark.asyncio
async def test_user_payload_contains_approved_assets(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(
        client=client,
        prompt_path=pp,
        approved_asset_ids=frozenset({"asset-1"}),
    )
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert "approved_asset_ids" in client.last_user_payload
    assert "asset-1" in client.last_user_payload["approved_asset_ids"]


# ── Prompt caching ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_cached_after_first_read(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    pp.unlink()
    await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
    assert client.call_count == 2


# ── Public properties ─────────────────────────────────────────────────────────


def test_prompt_version_property(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    planner = _make_planner(prompt_path=pp)
    assert planner.prompt_version == PROMPT_VERSION


def test_model_property(tmp_path: Path) -> None:
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_valid_draft(), prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp, model="custom-model")
    assert planner.model == "custom-model"


# ── Invalid draft rejected ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_affordance_in_draft_raises(tmp_path: Path) -> None:
    from learning_pipeline.planners.modality.video.validation import VideoModalityDraftValidationError
    bad_draft = VideoModalityDraft(
        draft_id="bad",
        title="Bad",
        narrative="Bad.",
        scenes=(VideoSceneDraft(
            scene_id="s",
            source_content=(_REF,),
            learning_objective="X",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="unknown_affordance",
            teaching_pattern="direct_instruction",
            content_direction="Teach X.",
            presentation_direction="Avatar.",
            target_duration_seconds=60,
        ),),
    )
    pp = tmp_path / "video_v1.md"
    pp.write_text("# prompt", encoding="utf-8")
    client = FakePlanningClient(draft=bad_draft, prompt_version="video_modality_v1")
    planner = VideoModalityPlanner(client=client, prompt_path=pp)
    with pytest.raises(VideoModalityPlannerError, match="validation"):
        await planner.create_modality_plan(_BLUEPRINT, Modality.VIDEO, _CONTEXT, _AFFORDANCE_VIEW)
