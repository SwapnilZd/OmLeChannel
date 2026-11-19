"""Proficiency and depth tests — Phase 12."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts.common import ContentDepth, TopicProficiency
from learning_pipeline.contracts.learner import LearnerContext
from learning_pipeline.contracts.rlo import RLODocument
from learning_pipeline.planners.curriculum.context import build_assembly_context
from learning_pipeline.planners.curriculum.proficiency import derive_starting_proficiency

_RLO_PATH = (
    Path(__file__).parents[3]
    / "examples" / "reference" / "rlos"
    / "rlo-adkar-01-name-and-sequence_v1.1.0.json"
)

_TOPIC = "ADKAR Change Model — Element Names and Order"


def _load_rlo() -> RLODocument:
    return RLODocument.model_validate_json(_RLO_PATH.read_text(encoding="utf-8"))


def _learner(
    default: TopicProficiency = TopicProficiency.BEGINNER,
    topic_profs: dict | None = None,
    level: int | None = 55,
) -> LearnerContext:
    return LearnerContext(
        role="Manager",
        deloitte_level=level,
        default_proficiency=default,
        topic_proficiencies=topic_profs or {},
        goals=("Learn ADKAR",),
    )


def test_topic_specific_proficiency_wins():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    learner = _learner(
        default=TopicProficiency.BEGINNER,
        topic_profs={_TOPIC: TopicProficiency.ADVANCED},
    )
    prof, source = derive_starting_proficiency(learner, ctx)
    assert prof == TopicProficiency.ADVANCED
    assert source == "topic_specific"


def test_default_proficiency_when_no_topic_match():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    learner = _learner(default=TopicProficiency.INTERMEDIATE)
    prof, source = derive_starting_proficiency(learner, ctx)
    assert prof == TopicProficiency.INTERMEDIATE
    assert source == "default"


def test_deloitte_level_does_not_determine_proficiency():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    # Level 65 (senior) with beginner default → still beginner
    learner_senior = _learner(default=TopicProficiency.BEGINNER, level=65)
    # Level 25 (junior) with advanced default → still advanced
    learner_junior = _learner(default=TopicProficiency.ADVANCED, level=25)

    prof_senior, _ = derive_starting_proficiency(learner_senior, ctx)
    prof_junior, _ = derive_starting_proficiency(learner_junior, ctx)
    assert prof_senior == TopicProficiency.BEGINNER
    assert prof_junior == TopicProficiency.ADVANCED


def test_proficiency_and_depth_are_independent_values():
    # ContentDepth.SUMMARY is not the same concept as TopicProficiency.BEGINNER
    assert ContentDepth.SUMMARY != TopicProficiency.BEGINNER
    assert ContentDepth.COMPREHENSIVE != TopicProficiency.ADVANCED


def test_source_label_is_topic_specific_for_exact_match():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    learner = _learner(topic_profs={_TOPIC: TopicProficiency.INTERMEDIATE})
    _, source = derive_starting_proficiency(learner, ctx)
    assert source == "topic_specific"


def test_source_label_is_default_for_fallback():
    rlo = _load_rlo()
    ctx = build_assembly_context(rlo)
    learner = _learner(topic_profs={})
    _, source = derive_starting_proficiency(learner, ctx)
    assert source == "default"
