"""Tests for PodcastModalityPlanner — Phase 10."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_pipeline.affordances.catalog import PlannerAffordanceView
from learning_pipeline.affordances.podcast import (
    PODCAST_SUPPORT_RULES,
    build_podcast_affordance_catalog,
    compute_producible_affordances,
)
from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    ModalityPlanningContext,
    NarrativeRole,
    PodcastModalityDraft,
    PodcastSceneDraft,
    ResolvedContentItem,
    ResolvedRLOContext,
)
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.planners.client import FakePlanningClient
from learning_pipeline.planners.modality.podcast.planner import (
    PROMPT_VERSION,
    PodcastModalityPlanner,
    PodcastModalityPlannerError,
)

_BP_PATH = Path(__file__).parents[3] / "examples" / "reference" / "podcast" / "course_blueprint.json"
_RLO_ROOT = Path(__file__).parents[3] / "examples" / "reference" / "rlos"
_PODCAST_CAPS = frozenset({"speech.synthesize", "audio.assemble"})


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_affordance_view() -> PlannerAffordanceView:
    catalog = build_podcast_affordance_catalog()
    return compute_producible_affordances(catalog, PODCAST_SUPPORT_RULES, _PODCAST_CAPS, Modality.PODCAST)


def _make_learner() -> LearnerContext:
    return LearnerContext(
        role="Manager",
        deloitte_level=55,
        default_proficiency="beginner",
        topic_proficiencies={},
        goals=["test"],
        duration_limit_minutes=10,
        business_context={},
    )


def _make_rlo_context(rlo_id: str = "rlo-adkar-01-name-and-sequence") -> ResolvedRLOContext:
    return ResolvedRLOContext(
        rlo_id=rlo_id,
        rlo_version="1.1.0",
        order=1,
        title="ADKAR",
        topic="Change Management",
        terminal_objective_text="Understand ADKAR",
        enabling_objectives=(ResolvedContentItem(
            rlo_id=rlo_id, rlo_version="1.1.0", content_type="objective",
            content_id="lo-01", title=None, content="Name the five ADKAR elements",
        ),),
        concepts=(ResolvedContentItem(
            rlo_id=rlo_id, rlo_version="1.1.0", content_type="concept",
            content_id="c-01", title="ADKAR", content="The ADKAR model",
        ),),
        components=(
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="component",
                                content_id="comp-hook-01", title="Hook", content="hook content"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="component",
                                content_id="comp-rule-01", title="Rule", content="rule content"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="component",
                                content_id="comp-example-01", title="Example 1", content="eg 1"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="component",
                                content_id="comp-example-02", title="Example 2", content="eg 2"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="component",
                                content_id="comp-nonexample-01", title="Non-example", content="non-eg"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="component",
                                content_id="comp-recall-01", title="Recall", content="recall"),
        ),
        assessment_items=(
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="assessment_item",
                                content_id="q-01", title="Q1", content="Q1 content"),
            ResolvedContentItem(rlo_id=rlo_id, rlo_version="1.1.0", content_type="assessment_item",
                                content_id="q-02", title="Q2", content="Q2 content"),
        ),
        selected_objective_ids=("lo-01",),
        selected_concept_ids=("c-01",),
        selected_component_ids=("comp-hook-01", "comp-rule-01", "comp-example-01",
                                "comp-example-02", "comp-nonexample-01", "comp-recall-01"),
        selected_assessment_ids=("q-01", "q-02"),
        role_relevance="Relevant to managers",
        example_context=None,
        adaptation_instructions=(),
    )


def _make_context() -> ModalityPlanningContext:
    return ModalityPlanningContext(
        blueprint_id="bp-adkar-01-podcast-manager-l55",
        learner=_make_learner(),
        rlo_contexts=(_make_rlo_context(),),
        estimated_duration_minutes=10,
    )


def _make_valid_draft() -> PodcastModalityDraft:
    rlo_id = "rlo-adkar-01-name-and-sequence"
    return PodcastModalityDraft(
        draft_id="test-modality-draft",
        title="ADKAR Podcast",
        narrative="A podcast covering ADKAR fundamentals for managers.",
        scenes=(
            PodcastSceneDraft(
                scene_id="scene-intro",
                source_content=(RLOContentRef(
                    rlo_id=rlo_id,
                    rlo_version="1.1.0",
                    objective_ids=("lo-01",),
                    concept_ids=("c-01",),
                    component_ids=("comp-hook-01", "comp-rule-01", "comp-example-01"),
                    assessment_item_ids=(),
                ),),
                learning_objective="Name the five ADKAR elements",
                narrative_role=NarrativeRole.EXPLANATION,
                affordance_id="host_expert_dialogue",
                teaching_pattern="hook_then_rule",
                content_direction="Introduce ADKAR elements with a hook and clear rule.",
                target_duration_seconds=240,
            ),
            PodcastSceneDraft(
                scene_id="scene-apply",
                source_content=(RLOContentRef(
                    rlo_id=rlo_id,
                    rlo_version="1.1.0",
                    objective_ids=(),
                    concept_ids=(),
                    component_ids=("comp-example-02", "comp-nonexample-01", "comp-recall-01"),
                    assessment_item_ids=("q-01", "q-02"),
                ),),
                learning_objective="Apply ADKAR to workplace scenarios",
                narrative_role=NarrativeRole.ASSESSMENT,
                affordance_id="spoken_knowledge_check",
                teaching_pattern="example_nonexample",
                content_direction="Walk through examples and non-examples, then quiz.",
                target_duration_seconds=240,
            ),
        ),
    )


def _make_planner(draft=None, prompt_path=None, tmp_path=None) -> tuple[PodcastModalityPlanner, FakePlanningClient]:
    d = draft or _make_valid_draft()
    client = FakePlanningClient(draft=d, prompt_version="podcast_modality_v1")
    pp = (tmp_path or Path("/tmp")) / "podcast_modality_v1.md"
    if not pp.exists():
        pp.write_text("# Test modality prompt", encoding="utf-8")
    planner = PodcastModalityPlanner(client=client, prompt_path=pp)
    return planner, client


def test_prompt_version_invalidates_prior_cached_plans(tmp_path: Path) -> None:
    planner, _ = _make_planner(tmp_path=tmp_path)
    assert PROMPT_VERSION == "podcast_modality_v6"
    assert planner.prompt_version == "podcast_modality_v6"


def test_default_prompt_plans_a_focused_host_expert_interview() -> None:
    from learning_pipeline.planners.modality.podcast.planner import _DEFAULT_PROMPT_PATH

    prompt = _DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
    assert "short, focused illustration or explanation" in prompt
    assert "genuine Host–Expert interview" in prompt
    assert "Never direct the Host to teach" in prompt
    assert "topic-relevant specialist role" in prompt
    assert "Expert to ask the Host" in prompt
    assert "silent listener-response gap" in prompt


# ── Return types ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_modality_plan(tmp_path: Path) -> None:
    planner, _ = _make_planner(tmp_path=tmp_path)
    plan = await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert isinstance(plan, ModalityPlan)


@pytest.mark.asyncio
async def test_plan_modality_is_podcast(tmp_path: Path) -> None:
    planner, _ = _make_planner(tmp_path=tmp_path)
    plan = await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert plan.modality == Modality.PODCAST


@pytest.mark.asyncio
async def test_plan_has_scenes(tmp_path: Path) -> None:
    planner, _ = _make_planner(tmp_path=tmp_path)
    plan = await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert len(plan.scenes) >= 1


# ── One-call rule ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exactly_one_client_call(tmp_path: Path) -> None:
    planner, client = _make_planner(tmp_path=tmp_path)
    assert client.call_count == 0
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert client.call_count == 1


# ── Wrong modality ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_modality_raises(tmp_path: Path) -> None:
    planner, _ = _make_planner(tmp_path=tmp_path)
    with pytest.raises(PodcastModalityPlannerError, match="podcast"):
        await planner.create_modality_plan(
            _load_blueprint(), Modality.VIDEO, _make_context(), _make_affordance_view()
        )


# ── Missing prompt file ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_prompt_file_raises(tmp_path: Path) -> None:
    client = FakePlanningClient(draft=_make_valid_draft(), prompt_version="podcast_modality_v1")
    planner = PodcastModalityPlanner(client=client, prompt_path=tmp_path / "nonexistent.md")
    with pytest.raises(PodcastModalityPlannerError, match="Cannot load"):
        await planner.create_modality_plan(
            _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
        )


# ── Prompt caching ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_file_read_only_once(tmp_path: Path) -> None:
    pp = tmp_path / "podcast_modality_v1.md"
    pp.write_text("# Prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_make_valid_draft(), prompt_version="podcast_modality_v1")
    planner = PodcastModalityPlanner(client=client, prompt_path=pp)
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    pp.unlink()  # delete file — second call should use cached prompt
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert client.call_count == 2


# ── Payload content ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_prompt_passed_to_client(tmp_path: Path) -> None:
    pp = tmp_path / "podcast_modality_v1.md"
    pp.write_text("# My modality prompt", encoding="utf-8")
    client = FakePlanningClient(draft=_make_valid_draft(), prompt_version="podcast_modality_v1")
    planner = PodcastModalityPlanner(client=client, prompt_path=pp)
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert client.last_system_prompt == "# My modality prompt"


@pytest.mark.asyncio
async def test_user_payload_contains_blueprint_id(tmp_path: Path) -> None:
    planner, client = _make_planner(tmp_path=tmp_path)
    ctx = _make_context()
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, ctx, _make_affordance_view()
    )
    assert client.last_user_payload is not None
    assert client.last_user_payload.get("blueprint_id") == ctx.blueprint_id


@pytest.mark.asyncio
async def test_user_payload_contains_affordances(tmp_path: Path) -> None:
    planner, client = _make_planner(tmp_path=tmp_path)
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    assert client.last_user_payload is not None
    assert "affordances" in client.last_user_payload


@pytest.mark.asyncio
async def test_user_payload_contains_no_production_task_types(tmp_path: Path) -> None:
    planner, client = _make_planner(tmp_path=tmp_path)
    await planner.create_modality_plan(
        _load_blueprint(), Modality.PODCAST, _make_context(), _make_affordance_view()
    )
    payload_str = json.dumps(client.last_user_payload)
    # Raw production capability names must not appear in the payload
    assert "speech.synthesize" not in payload_str
    assert "audio.assemble" not in payload_str
