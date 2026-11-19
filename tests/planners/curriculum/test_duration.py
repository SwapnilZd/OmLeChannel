"""Duration estimation policy tests — Phase 12."""
from __future__ import annotations

from pathlib import Path

from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.curriculum_assembly import TailoredRLODraft
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.context import build_assembly_context
from learning_pipeline.planners.curriculum.duration import (
    DURATION_POLICY_VERSION,
    estimate_rlo_duration,
    estimate_total_duration,
)

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _draft(
    depth: ContentDepth = ContentDepth.WORKING,
    target: TopicProficiency = TopicProficiency.INTERMEDIATE,
    sel: RLOContentSelection | None = None,
) -> TailoredRLODraft:
    rlo = _load_rlo()
    return TailoredRLODraft(
        rlo_id=rlo.id,
        rlo_version=rlo.version,
        order=1,
        selected_content=sel or RLOContentSelection(),
        target_proficiency=target,
        content_depth=depth,
        role_relevance="Relevant.",
        personalization_rationale="For learner goals.",
        sequencing_rationale="First.",
    )


def test_policy_version_recorded():
    assert DURATION_POLICY_VERSION == "duration_v1"


def test_duration_is_positive():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    d = estimate_rlo_duration(_draft(), ctx, TopicProficiency.BEGINNER)
    assert d > 0


def test_summary_depth_reduces_duration():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    summary = estimate_rlo_duration(
        _draft(depth=ContentDepth.SUMMARY), ctx, TopicProficiency.BEGINNER
    )
    working = estimate_rlo_duration(
        _draft(depth=ContentDepth.WORKING), ctx, TopicProficiency.BEGINNER
    )
    assert summary < working


def test_comprehensive_depth_increases_duration():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    working = estimate_rlo_duration(
        _draft(depth=ContentDepth.WORKING), ctx, TopicProficiency.BEGINNER
    )
    comprehensive = estimate_rlo_duration(
        _draft(depth=ContentDepth.COMPREHENSIVE), ctx, TopicProficiency.BEGINNER
    )
    assert comprehensive > working


def test_proficiency_gap_increases_duration():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    no_gap = estimate_rlo_duration(
        _draft(target=TopicProficiency.INTERMEDIATE), ctx, TopicProficiency.INTERMEDIATE
    )
    big_gap = estimate_rlo_duration(
        _draft(target=TopicProficiency.ADVANCED), ctx, TopicProficiency.BEGINNER
    )
    assert big_gap > no_gap


def test_duration_is_deterministic():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    d1 = estimate_rlo_duration(_draft(), ctx, TopicProficiency.BEGINNER)
    d2 = estimate_rlo_duration(_draft(), ctx, TopicProficiency.BEGINNER)
    assert d1 == d2


def test_total_duration_sums_rlos():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    d = _draft()
    total = estimate_total_duration(
        (d,),
        {rlo.id: ctx},
        {rlo.id: TopicProficiency.BEGINNER},
    )
    assert total == estimate_rlo_duration(d, ctx, TopicProficiency.BEGINNER)


def test_bridge_time_adds_to_total():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    no_bridge = estimate_total_duration(
        (_draft(),), {rlo.id: ctx}, {rlo.id: TopicProficiency.BEGINNER}, bridge_count=0
    )
    with_bridge = estimate_total_duration(
        (_draft(),), {rlo.id: ctx}, {rlo.id: TopicProficiency.BEGINNER}, bridge_count=1
    )
    assert with_bridge > no_bridge
