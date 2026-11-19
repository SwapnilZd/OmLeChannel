from __future__ import annotations

import json
from pathlib import Path

import pytest

from learning_commissioning.adapters import RLOCompatibilityError, adapt_stored_rlo
from learning_pipeline.contracts import RLODocument
from rlo_schema import validate_rlo

_ROOT = Path(__file__).parents[2]
_RLOS = _ROOT / "course-definitions/rlos"


def _raw(name: str = "rlo-adkar-04-awareness.json") -> dict:
    return json.loads((_RLOS / name).read_text(encoding="utf-8"))


def test_every_stored_rlo_adapts_to_curriculum_contract():
    files = sorted(_RLOS.glob("*.json"))
    assert len(files) == 25
    for path in files:
        shared, _ = validate_rlo(json.loads(path.read_text(encoding="utf-8")))
        adapted = adapt_stored_rlo(shared)
        assert isinstance(adapted, RLODocument)
        assert adapted.id == shared.id
        assert adapted.version == shared.version
        assert shared.governance.status.value == "approved"
        assert adapted.governance.status == "approved"


def test_smart_goals_seed_preserves_framework_and_context_variants():
    shared, _ = validate_rlo(_raw("rlo-smart-goals-01-construct.json"))
    adapted = adapt_stored_rlo(shared)

    assert adapted.id == "rlo-smart-goals-01-construct"
    assert adapted.version == "1.0.0"
    assert adapted.enabling_objective.bloom_level == "create"
    assert {concept.name for concept in adapted.concepts} == {
        "Specific",
        "Measurable",
        "Achievable",
        "Relevant",
        "Time-bound",
    }
    assert {variant["industry_tags"][0] for variant in adapted.variant_examples} == {
        "financial_services",
        "manufacturing",
    }
    assert all(item.options for item in adapted.assessment_items)


@pytest.mark.parametrize(
    ("filename", "rlo_id", "concept_names"),
    [
        (
            "rlo-raci-matrix-01-assign.json",
            "rlo-raci-matrix-01-assign",
            {"Responsible", "Accountable", "Consulted", "Informed", "RACI matrix structural rules"},
        ),
        (
            "rlo-swot-analysis-01-assess.json",
            "rlo-swot-analysis-01-assess",
            {"Strengths", "Weaknesses", "Opportunities", "Threats", "TOWS strategy combinations"},
        ),
    ],
)
def test_new_framework_seeds_preserve_core_concepts_and_context_variants(
    filename, rlo_id, concept_names
):
    shared, _ = validate_rlo(_raw(filename))
    adapted = adapt_stored_rlo(shared)

    assert adapted.id == rlo_id
    assert adapted.version == "1.0.0"
    assert {concept.name for concept in adapted.concepts} == concept_names
    assert {variant["industry_tags"][0] for variant in adapted.variant_examples} == {
        "financial_services",
        "manufacturing",
    }
    assert all(item.options for item in adapted.assessment_items)


def test_list_shaped_canonical_content_returns_typed_incompatibility():
    raw = _raw()
    raw["components"][0]["canonical_content"] = ["unsupported", "downstream"]
    shared, _ = validate_rlo(raw)
    with pytest.raises(RLOCompatibilityError, match="list-shaped"):
        adapt_stored_rlo(shared)


def test_open_response_returns_typed_incompatibility():
    raw = _raw()
    item = raw["assessment_items"][0]
    item["type"] = "open_response"
    item["options"] = None
    item["correct_response"] = "A full-credit response explains the distinction."
    item["scoring_criteria"] = "Award credit for a grounded explanation."
    item["feedback_guidance"] = "Name the missing distinction."
    shared, _ = validate_rlo(raw)
    with pytest.raises(RLOCompatibilityError, match="open-response"):
        adapt_stored_rlo(shared)


def test_multiple_references_for_any_gagne_event_survive_adapter():
    raw = _raw()
    component_ids = [component["id"] for component in raw["components"][:2]]
    raw["gagne_event_mapping"]["event_1_gain_attention"] = component_ids
    raw["gagne_event_mapping"]["event_3_stimulate_recall"] = component_ids

    adapted = adapt_stored_rlo(validate_rlo(raw)[0])

    assert adapted.gagne_event_mapping.event_1_gain_attention == tuple(component_ids)
    assert adapted.gagne_event_mapping.event_3_stimulate_recall == tuple(component_ids)


def test_claim_level_evidence_survives_commissioning_adapter():
    raw = _raw()
    source = raw["sources"][0]
    source.update(
        {
            "ingested_source_id": "source-adkar-primary",
            "source_version_id": "source-adkar-primary-v1",
            "checksum": "1" * 64,
            "canonical_locator": source["title"],
        }
    )
    raw["evidence"] = [
        {
            "id": "ev-objective",
            "source_ref": source["id"],
            "source_version_id": "source-adkar-primary-v1",
            "node_ids": ["node-adkar-overview"],
            "segment_ids": ["segment-adkar-overview"],
            "locator": "ADKAR overview",
            "role": "objective_defining",
        }
    ]
    raw["enabling_objective"]["evidence_refs"] = ["ev-objective"]
    raw["concepts"][0]["evidence_refs"] = ["ev-objective"]
    raw["components"][0]["evidence_refs"] = ["ev-objective"]
    raw["assessment_items"][0]["evidence_refs"] = ["ev-objective"]
    raw["assessment_items"][0]["options"][0]["evidence_refs"] = ["ev-objective"]

    adapted = adapt_stored_rlo(validate_rlo(raw)[0])

    assert adapted.sources[0].source_version_id == "source-adkar-primary-v1"
    assert adapted.evidence[0].node_ids == ("node-adkar-overview",)
    assert adapted.evidence[0].segment_ids == ("segment-adkar-overview",)
    assert adapted.enabling_objective.evidence_refs == ("ev-objective",)
    assert adapted.components[0].evidence_refs == ("ev-objective",)
    assert adapted.assessment_items[0].options[0].evidence_refs == ("ev-objective",)
