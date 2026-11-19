import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from constraints import (  # noqa: E402
    OVER, UNDER, TOO_MANY, TOO_FEW,
    validate_budgets, format_violations,
)

# A descriptor mirroring the concept_flip_card shape: scalar slots + an array
# slot with nested item_slots and a scalar-array item slot.
DESCRIPTOR = {
    "slots": {
        "section_label": {"target_chars": 40, "min_chars": 10, "max_chars": 60},
        "instruction": {"target_chars": 60, "max_chars": 100},
        "cards": {
            "type": "array",
            "min_items": 2,
            "max_items": 4,
            "item_slots": {
                "front_label": {"max_chars": 40},
                "back_definition": {"min_chars": 40, "max_chars": 200},
                "back_examples": {"type": "array", "min_items": 1, "max_items": 2, "item_max_chars": 100},
            },
        },
    }
}


def _good_content():
    return {
        "section_label": "Independence Threats",
        "instruction": "Click each card to explore the threat category.",
        "cards": [
            {
                "front_label": "Self-review",
                "back_definition": "Reviewing your own prior work impairs objectivity because you are unlikely to fault it.",
                "back_examples": ["Auditing a system you built"],
            },
            {
                "front_label": "Advocacy",
                "back_definition": "Promoting a client's position can compromise the appearance of impartiality in later judgements.",
                "back_examples": ["Representing a client in a dispute", "Marketing a client's shares"],
            },
        ],
    }


def test_clean_content_has_no_violations():
    assert validate_budgets(_good_content(), DESCRIPTOR) == []


def test_over_max_chars():
    c = _good_content()
    c["section_label"] = "x" * 80
    vs = validate_budgets(c, DESCRIPTOR)
    assert any(v.kind == OVER and v.path == "section_label" and v.bound == 60 for v in vs)


def test_under_explicit_min_chars():
    c = _good_content()
    c["cards"][0]["back_definition"] = "Too short."
    vs = validate_budgets(c, DESCRIPTOR)
    assert any(v.kind == UNDER and v.path == "cards[0].back_definition" for v in vs)


def test_too_few_and_too_many_items():
    c = _good_content()
    c["cards"] = [c["cards"][0]]  # 1 card, min is 2
    assert any(v.kind == TOO_FEW and v.path == "cards" for v in validate_budgets(c, DESCRIPTOR))

    c = _good_content()
    c["cards"][0]["back_examples"] = ["a", "b", "c"]  # max 2
    assert any(v.kind == TOO_MANY and v.path == "cards[0].back_examples" for v in validate_budgets(c, DESCRIPTOR))


def test_nested_item_max_chars():
    c = _good_content()
    c["cards"][0]["back_examples"] = ["y" * 150]  # item_max_chars 100
    vs = validate_budgets(c, DESCRIPTOR)
    assert any(v.kind == OVER and v.path == "cards[0].back_examples[0]" for v in vs)


def test_scalar_array_item_slots_are_validated():
    descriptor = {
        "slots": {
            "objectives": {
                "type": "array",
                "item_slots": {"text": {"max_chars": 20}},
            }
        }
    }
    vs = validate_budgets({"objectives": ["x" * 30]}, descriptor)
    assert any(v.kind == OVER and v.path == "objectives[0]" for v in vs)


def test_nested_object_slots_are_validated():
    descriptor = {
        "slots": {
            "acceptable": {
                "type": "object",
                "slots": {"description": {"max_chars": 20}},
            }
        }
    }
    vs = validate_budgets(
        {"acceptable": {"description": "x" * 30}},
        descriptor,
    )
    assert any(
        v.kind == OVER and v.path == "acceptable.description"
        for v in vs
    )


def test_derived_min_floor_recurses_into_object_slots():
    descriptor = {
        "slots": {
            "acceptable": {
                "type": "object",
                "slots": {"reason": {"target_chars": 50}},
            }
        }
    }
    vs = validate_budgets(
        {"acceptable": {"reason": "Brief."}},
        descriptor,
        min_char_floor_ratio=0.4,
    )
    assert any(
        v.kind == UNDER
        and v.path == "acceptable.reason"
        and v.bound == 20
        for v in vs
    )


def test_derived_min_floor_flags_thin_undeclared_slot():
    # `instruction` has target 60 but no explicit min; with a 0.4 floor a 5-char
    # value should be flagged as UNDER (floor = 24).
    c = _good_content()
    c["instruction"] = "Go."
    assert validate_budgets(c, DESCRIPTOR) == []  # no floor by default
    vs = validate_budgets(c, DESCRIPTOR, min_char_floor_ratio=0.4)
    assert any(v.kind == UNDER and v.path == "instruction" and v.bound == 24 for v in vs)


def test_format_violations_is_numbered_brief():
    c = _good_content()
    c["section_label"] = "x" * 80
    text = format_violations(validate_budgets(c, DESCRIPTOR))
    assert "1." in text and "section_label" in text
