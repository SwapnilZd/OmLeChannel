"""Tests for PodcastModalityPlanBuilder — Phase 10."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.modality import ModalityPlan, RLOContentRef
from learning_pipeline.contracts.planning import (
    NarrativeRole,
    PodcastModalityDraft,
    PodcastSceneDraft,
)
from learning_pipeline.planners.modality.podcast.builder import (
    PodcastModalityPlanBuilder,
    PodcastModalityPlanBuilderError,
)

_BP_PATH = Path(__file__).parents[3] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _make_scene(
    scene_id: str = "scene-01",
    rlo_id: str = "rlo-adkar-01-name-and-sequence",
    version: str = "1.1.0",
    duration: int = 180,
    role: NarrativeRole = NarrativeRole.EXPLANATION,
    affordance: str = "host_expert_dialogue",
) -> PodcastSceneDraft:
    return PodcastSceneDraft(
        scene_id=scene_id,
        source_content=(RLOContentRef(rlo_id=rlo_id, rlo_version=version),),
        learning_objective=f"Objective for {scene_id}",
        narrative_role=role,
        affordance_id=affordance,
        teaching_pattern="direct_instruction",
        content_direction="Teach the concept.",
        target_duration_seconds=duration,
    )


def _make_draft(scenes=None) -> PodcastModalityDraft:
    s = scenes or (_make_scene("scene-01"),)
    return PodcastModalityDraft(
        draft_id="test-draft-01",
        title="Test Episode",
        narrative="A test podcast episode.",
        scenes=s,
    )


# ── Return types ──────────────────────────────────────────────────────────────


def test_build_returns_modality_plan() -> None:
    blueprint = _load_blueprint()
    plan = PodcastModalityPlanBuilder().build(_make_draft(), blueprint)
    assert isinstance(plan, ModalityPlan)


def test_plan_modality_is_podcast() -> None:
    blueprint = _load_blueprint()
    plan = PodcastModalityPlanBuilder().build(_make_draft(), blueprint)
    assert plan.modality == Modality.PODCAST


# ── Plan ID ───────────────────────────────────────────────────────────────────


def test_plan_id_derived_from_draft_id() -> None:
    blueprint = _load_blueprint()
    plan = PodcastModalityPlanBuilder().build(_make_draft(), blueprint)
    assert plan.plan_id == "mp-test-draft-01"


# ── Narrative ─────────────────────────────────────────────────────────────────


def test_narrative_matches_draft() -> None:
    blueprint = _load_blueprint()
    plan = PodcastModalityPlanBuilder().build(_make_draft(), blueprint)
    assert plan.narrative == "A test podcast episode."


# ── Scene count and order ─────────────────────────────────────────────────────


def test_scene_count_matches_draft() -> None:
    blueprint = _load_blueprint()
    scenes = (_make_scene("s1"), _make_scene("s2"), _make_scene("s3"))
    plan = PodcastModalityPlanBuilder().build(_make_draft(scenes), blueprint)
    assert len(plan.scenes) == 3


def test_scene_order_preserved() -> None:
    blueprint = _load_blueprint()
    scenes = (_make_scene("alpha"), _make_scene("beta"), _make_scene("gamma"))
    plan = PodcastModalityPlanBuilder().build(_make_draft(scenes), blueprint)
    # IDs should appear in the same order
    ids = [s.id for s in plan.scenes]
    assert ids == ["alpha", "beta", "gamma"]


# ── Scene field preservation ──────────────────────────────────────────────────


def test_learning_objective_preserved() -> None:
    blueprint = _load_blueprint()
    scene = _make_scene("s1")
    plan = PodcastModalityPlanBuilder().build(_make_draft((scene,)), blueprint)
    assert plan.scenes[0].learning_objective == "Objective for s1"


def test_source_content_preserved() -> None:
    blueprint = _load_blueprint()
    plan = PodcastModalityPlanBuilder().build(_make_draft(), blueprint)
    assert plan.scenes[0].source_content[0].rlo_id == "rlo-adkar-01-name-and-sequence"


def test_affordance_id_becomes_preferred_capability() -> None:
    blueprint = _load_blueprint()
    plan = PodcastModalityPlanBuilder().build(_make_draft(), blueprint)
    assert plan.scenes[0].preferred_capability == "host_expert_dialogue"


def test_narrative_role_preserved() -> None:
    blueprint = _load_blueprint()
    scene = _make_scene("s1", role=NarrativeRole.HOOK)
    plan = PodcastModalityPlanBuilder().build(_make_draft((scene,)), blueprint)
    assert plan.scenes[0].narrative_role == "hook"


def test_target_duration_preserved() -> None:
    blueprint = _load_blueprint()
    scene = _make_scene("s1", duration=240)
    plan = PodcastModalityPlanBuilder().build(_make_draft((scene,)), blueprint)
    assert plan.scenes[0].target_duration_seconds == 240


# ── Optional fields ───────────────────────────────────────────────────────────


def test_learner_engagement_preserved() -> None:
    blueprint = _load_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(RLOContentRef(rlo_id="rlo-adkar-01-name-and-sequence", rlo_version="1.1.0"),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="d",
            target_duration_seconds=60,
            learner_engagement="Relate to your team's change resistance",
        ),),
    )
    plan = PodcastModalityPlanBuilder().build(draft, blueprint)
    assert plan.scenes[0].learner_engagement == "Relate to your team's change resistance"


def test_transition_direction_preserved() -> None:
    blueprint = _load_blueprint()
    draft = PodcastModalityDraft(
        draft_id="d",
        title="T",
        narrative="N",
        scenes=(PodcastSceneDraft(
            scene_id="s1",
            source_content=(RLOContentRef(rlo_id="rlo-adkar-01-name-and-sequence", rlo_version="1.1.0"),),
            learning_objective="obj",
            narrative_role=NarrativeRole.EXPLANATION,
            affordance_id="host_expert_dialogue",
            teaching_pattern="direct",
            content_direction="d",
            target_duration_seconds=60,
            transition_direction="And now, let's apply this…",
        ),),
    )
    plan = PodcastModalityPlanBuilder().build(draft, blueprint)
    assert plan.scenes[0].transition_direction == "And now, let's apply this…"


# ── ID sanitization ───────────────────────────────────────────────────────────


def test_scene_id_sanitized_to_lowercase() -> None:
    blueprint = _load_blueprint()
    scene = _make_scene("Scene_ABC")
    plan = PodcastModalityPlanBuilder().build(_make_draft((scene,)), blueprint)
    assert plan.scenes[0].id == "scene_abc"


def test_special_chars_replaced_with_hyphens() -> None:
    blueprint = _load_blueprint()
    scene = _make_scene("scene 01! intro")
    plan = PodcastModalityPlanBuilder().build(_make_draft((scene,)), blueprint)
    assert " " not in plan.scenes[0].id
    assert "!" not in plan.scenes[0].id


def test_collision_in_sanitized_ids_raises() -> None:
    blueprint = _load_blueprint()
    scenes = (_make_scene("Scene One"), _make_scene("scene one"))
    with pytest.raises(PodcastModalityPlanBuilderError):
        PodcastModalityPlanBuilder().build(_make_draft(scenes), blueprint)


# ── Determinism ───────────────────────────────────────────────────────────────


def test_build_is_deterministic() -> None:
    blueprint = _load_blueprint()
    draft = _make_draft()
    builder = PodcastModalityPlanBuilder()
    plan1 = builder.build(draft, blueprint)
    plan2 = builder.build(draft, blueprint)
    assert plan1.model_dump_json() == plan2.model_dump_json()
