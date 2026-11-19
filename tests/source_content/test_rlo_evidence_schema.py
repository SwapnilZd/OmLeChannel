from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rlo_schema import RLO


_FIXTURES = Path(__file__).parent / "fixtures" / "rlo_lineage"


def _base_rlo() -> dict:
    return {
        "id": "rlo-coffee-brew",
        "version": "0.1.0",
        "schema_version": "1.0.0",
        "title": "Prepare coffee",
        "topic": "Coffee preparation",
        "domain": "Food preparation",
        "level": "introductory",
        "estimated_duration_minutes": 5,
        "content_type": "procedure",
        "performance_level": "do",
        "terminal_objective": "Prepare a cup of coffee using the available machine.",
        "performance_context": "When preparing coffee at work.",
        "enabling_objective": {
            "id": "lo-1",
            "statement": "Operate the machine to prepare coffee.",
            "bloom_level": "apply",
            "concepts_addressed": ["c-1"],
        },
        "concepts": [
            {
                "id": "c-1",
                "name": "Brew operation",
                "definition": "The machine extracts coffee after the brew control is pressed.",
                "elaboration": "Preparation requires the machine to be ready before extraction.",
                "source_refs": ["src-manual"],
                "misconceptions": [
                    {
                        "id": "m-1",
                        "statement": "Extraction begins before the brew control is pressed.",
                        "correction": "Pressing the brew control begins extraction.",
                    }
                ],
            }
        ],
        "components": [
            {
                "id": "comp-rule-1",
                "cdt_type": "rule",
                "concepts_referenced": ["c-1"],
                "misconceptions_addressed": ["m-1"],
                "canonical_content": "Press the brew control when the machine is ready.",
            }
        ],
        "assessment_items": [
            {
                "id": "q-1",
                "stem": "What begins extraction?",
                "type": "multiple_choice_single",
                "concepts_assessed": ["c-1"],
                "options": [
                    {
                        "id": "A",
                        "text": "Pressing the brew control",
                        "correct": True,
                        "misconception_targeted": None,
                        "feedback": "Correct.",
                    },
                    {
                        "id": "B",
                        "text": "Waiting without operating the machine",
                        "correct": False,
                        "misconception_targeted": "m-1",
                        "feedback": "The brew control must be pressed.",
                    },
                ],
            }
        ],
        "design_brief": {
            "tone": "Direct",
            "scaffolding_level": "low",
            "scaffolding_notes": "Assume no prior machine experience.",
            "feedback_policy": "Name the correct operating step.",
            "salience_hook_description": "Connect the procedure to preparing a reliable cup.",
        },
        "gagne_event_mapping": {"event_4_present_content": "comp-rule-1"},
        "authoring_rationale": "A small procedure for testing grounded RLO lineage.",
        "governance": {
            "status": "draft",
            "authoring_sme": "Example author",
            "change_history": "0.1.0 created",
        },
    }


def _lineaged_rlo(fixture_name: str = "single-source.json") -> dict:
    raw = _base_rlo()
    fixture = json.loads((_FIXTURES / fixture_name).read_text(encoding="utf-8"))
    raw["sources"] = fixture["sources"]
    raw["evidence"] = fixture["evidence"]
    refs = fixture["references"]
    raw["enabling_objective"]["evidence_refs"] = refs["enabling_objective"]
    raw["concepts"][0]["evidence_refs"] = refs["concept"]
    raw["concepts"][0]["misconceptions"][0]["evidence_refs"] = refs["misconception"]
    raw["components"][0]["evidence_refs"] = refs["component"]
    raw["assessment_items"][0]["evidence_refs"] = refs["assessment_item"]
    raw["assessment_items"][0]["options"][0]["evidence_refs"] = refs[
        "assessment_option"
    ]
    return raw


@pytest.mark.parametrize("fixture_name", ["single-source.json", "multi-source.json"])
def test_claim_level_lineage_validates(fixture_name: str) -> None:
    rlo = RLO.model_validate(_lineaged_rlo(fixture_name))
    assert rlo.enabling_objective.evidence_refs == ["ev-brew-procedure"]
    assert rlo.concepts[0].source_refs == ["src-manual"]
    if fixture_name == "multi-source.json":
        assert {item.source_version_id for item in rlo.evidence} == {
            "source-coffee-manual-v1",
            "source-colombian-soil-v1",
        }


def test_unknown_evidence_reference_is_rejected() -> None:
    raw = _lineaged_rlo()
    raw["components"][0]["evidence_refs"] = ["ev-missing"]
    with pytest.raises(ValidationError, match="unknown evidence"):
        RLO.model_validate(raw)


def test_unknown_source_and_source_version_mismatch_are_rejected() -> None:
    unknown = _lineaged_rlo()
    unknown["evidence"][0]["source_ref"] = "src-missing"
    with pytest.raises(ValidationError, match="unknown source"):
        RLO.model_validate(unknown)

    mismatched = _lineaged_rlo()
    mismatched["evidence"][0]["source_version_id"] = "different-version"
    with pytest.raises(ValidationError, match="source version does not match"):
        RLO.model_validate(mismatched)


def test_duplicate_evidence_ids_and_empty_node_references_are_rejected() -> None:
    duplicate = _lineaged_rlo()
    duplicate["evidence"].append(copy.deepcopy(duplicate["evidence"][0]))
    with pytest.raises(ValidationError, match="Evidence IDs must be unique"):
        RLO.model_validate(duplicate)

    empty_nodes = _lineaged_rlo()
    empty_nodes["evidence"][0]["node_ids"] = []
    with pytest.raises(ValidationError, match="node_ids"):
        RLO.model_validate(empty_nodes)


def test_duplicate_source_ids_are_rejected() -> None:
    raw = _lineaged_rlo("multi-source.json")
    raw["sources"][1]["id"] = raw["sources"][0]["id"]
    with pytest.raises(ValidationError, match="Source IDs must be unique"):
        RLO.model_validate(raw)


def test_excerpt_hash_is_verified() -> None:
    raw = _lineaged_rlo()
    raw["evidence"][0]["excerpt"] = "Changed excerpt"
    with pytest.raises(ValidationError, match="excerpt_sha256 does not match"):
        RLO.model_validate(raw)


def test_evidence_excerpt_can_exceed_legacy_character_limit() -> None:
    raw = _lineaged_rlo()
    excerpt = "Header " + (" " * 2_100) + "substantive table row"
    raw["evidence"][0]["excerpt"] = excerpt
    raw["evidence"][0]["excerpt_sha256"] = hashlib.sha256(excerpt.encode()).hexdigest()
    raw["evidence"][0]["segment_ids"] = ["segment-1"]

    rlo = RLO.model_validate(raw)

    assert rlo.evidence[0].excerpt == excerpt
    assert rlo.evidence[0].segment_ids == ["segment-1"]


def test_supporting_context_cannot_define_assessment_scope() -> None:
    raw = _lineaged_rlo("multi-source.json")
    raw["assessment_items"][0]["evidence_refs"] = ["ev-soil-flavor"]
    with pytest.raises(ValidationError, match="cannot use supporting-context evidence"):
        RLO.model_validate(raw)
