"""Structural guardrails for the topic-neutral authoring evaluation matrix."""
from __future__ import annotations

import json
from pathlib import Path


_CASES = Path(__file__).parent / "fixtures" / "authoring_evaluation_cases.json"


def test_evaluation_set_covers_required_source_shapes_and_runtime_boundaries():
    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    case_ids = {case["case_id"] for case in cases}
    all_families = {
        family for case in cases for family in case["required_screen_families"]
    }
    all_gates = {gate for case in cases for gate in case["quality_gates"]}

    assert len(cases) >= 8
    assert len(case_ids) == len(cases)
    assert {"knowledge_check", "scenario_setup", "relationship_diagram", "video_slot"} <= all_families
    assert {
        "source_fidelity",
        "assessment_fidelity",
        "screen_budget",
        "scoped_patch",
        "checkpoint_resume",
        "bounded_calls",
    } <= all_gates


def test_evaluation_cases_are_topic_neutral_and_have_manual_quality_gates():
    cases = json.loads(_CASES.read_text(encoding="utf-8"))

    assert all(case["source_shape"] for case in cases)
    assert all(case["quality_gates"] for case in cases)
    assert not any(
        topic in json.dumps(cases).lower()
        for topic in ("kotter", "adkar", "deloitte example")
    )
