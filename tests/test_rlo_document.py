import json
import pathlib

import pytest
from pydantic import ValidationError

from learning_pipeline.contracts import (
    CourseBlueprint,
    DesignBrief,
    GagneEventMapping,
    InstructionalComponent,
    LearnerContext,
    ModalityScene,
    RLOContentRef,
    RLOContentSelection,
    TailoredRLORef,
    TopicProficiency,
)

_RLO_DIR = pathlib.Path(__file__).parent.parent / "course-definitions" / "rlos"


def _load_rlo(name: str) -> dict:
    return json.loads((_RLO_DIR / name).read_text())


# ── Test 1: Example JSON validates as RLODocument ────────────────────────────

def test_example_rlo_json_validates_as_rlo_document() -> None:
    from learning_pipeline.contracts import RLODocument
    data = _load_rlo("rlo-adkar-04-awareness.json")
    doc = RLODocument.model_validate(data)
    assert doc.id == "rlo-adkar-04-awareness"
    assert doc.version == "1.1.0"
    assert len(doc.concepts) == 2
    assert len(doc.components) == 8
    assert len(doc.assessment_items) == 2
    assert doc.gagne_event_mapping.event_4_present_content == ("comp-rule-01", "comp-rule-02")


# ── Test 2: extra="forbid" catches schema drift ──────────────────────────────

def test_rlo_document_rejects_unknown_fields() -> None:
    from learning_pipeline.contracts import RLODocument
    data = _load_rlo("rlo-adkar-04-awareness.json")
    data["unexpected_field"] = "drift"
    with pytest.raises(ValidationError):
        RLODocument.model_validate(data)


# ── Test 3: Component accepts dict canonical_content ────────────────────────

def test_component_with_dict_canonical_content_is_accepted() -> None:
    comp = InstructionalComponent(
        id="comp-1",
        cdt_type="example",
        title="Example title",
        concepts_referenced=("c-01",),
        canonical_content={"setup": "A scenario", "reasoning": "Because of X"},
    )
    assert isinstance(comp.canonical_content, dict)
    assert comp.canonical_content["setup"] == "A scenario"


# ── Test 4: GagneEventMapping coerces list fields to tuples ─────────────────

def test_gagne_event_list_fields_coerce_to_tuples() -> None:
    mapping = GagneEventMapping.model_validate({
        "event_4_present_content": ["comp-rule-01", "comp-rule-02"],
        "event_5_provide_guidance": ["comp-example-01"],
        "event_6_elicit_performance": ["comp-recall-01"],
        "event_8_assess_performance": ["q-01", "q-02"],
    })
    assert isinstance(mapping.event_4_present_content, tuple)
    assert mapping.event_4_present_content == ("comp-rule-01", "comp-rule-02")
    assert mapping.event_8_assess_performance == ("q-01", "q-02")
    assert mapping.event_3_stimulate_recall == ()


def test_gagne_event_single_references_are_normalized_to_tuples() -> None:
    mapping = GagneEventMapping.model_validate({
        "event_1_gain_attention": "comp-hook-01",
        "event_7_provide_feedback": "comp-practice-01",
    })
    assert mapping.event_1_gain_attention == ("comp-hook-01",)
    assert mapping.event_7_provide_feedback == ("comp-practice-01",)


# ── Test 5: RLOContentSelection defaults all empty ───────────────────────────

def test_rlo_content_selection_defaults_all_empty() -> None:
    sel = RLOContentSelection()
    assert sel.objective_ids == ()
    assert sel.concept_ids == ()
    assert sel.component_ids == ()
    assert sel.assessment_item_ids == ()


# ── Test 6: CourseBlueprint rejects duplicate orders ────────────────────────

def test_blueprint_rejects_duplicate_rlo_orders() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _make_two_ref_blueprint(order_a=1, order_b=1)


# ── Test 7: CourseBlueprint rejects non-positive orders ─────────────────────

def test_blueprint_rejects_non_positive_rlo_order() -> None:
    with pytest.raises(ValidationError, match="positive"):
        _make_two_ref_blueprint(order_a=0, order_b=1)


# ── Test 8: CourseBlueprint source_rlo_versions must match refs ──────────────

def test_blueprint_rejects_mismatched_source_rlo_versions() -> None:
    ref = _make_ref("rlo-1", "v1", order=1)
    learner = LearnerContext(
        role="analyst",
        default_proficiency=TopicProficiency.BEGINNER,
        goals=("learn",),
    )
    with pytest.raises(ValidationError, match="source_rlo_versions"):
        CourseBlueprint(
            blueprint_id="bp-1",
            learner=learner,
            title="Test",
            learning_outcomes=("Outcome",),
            ordered_rlo_refs=(ref,),
            sequencing_rationale="in order",
            assessment_strategy="quiz at end",
            estimated_duration_minutes=30,
            source_rlo_versions={"rlo-1": "v99"},
        )


# ── Test 9: ModalityScene requires at least one source_content ref ───────────

def test_modality_scene_requires_non_empty_source_content() -> None:
    with pytest.raises(ValidationError, match="source_content"):
        ModalityScene(
            id="s-1",
            source_content=(),
            learning_objective="obj",
            teaching_pattern="explanation",
            preferred_capability="narrated_explanation",
            content_direction="dir",
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_ref(rlo_id: str, version: str, order: int) -> TailoredRLORef:
    return TailoredRLORef(
        rlo_id=rlo_id,
        rlo_version=version,
        order=order,
        selected_content=RLOContentSelection(),
        starting_proficiency=TopicProficiency.BEGINNER,
        target_proficiency=TopicProficiency.INTERMEDIATE,
        role_relevance="relevant",
        personalization_rationale="basic coverage",
        sequencing_rationale="first in sequence",
    )


def _make_two_ref_blueprint(order_a: int, order_b: int) -> CourseBlueprint:
    learner = LearnerContext(
        role="analyst",
        default_proficiency=TopicProficiency.BEGINNER,
        goals=("learn",),
    )
    ref_a = _make_ref("rlo-1", "v1", order=order_a)
    ref_b = _make_ref("rlo-2", "v1", order=order_b)
    return CourseBlueprint(
        blueprint_id="bp-1",
        learner=learner,
        title="Test Blueprint",
        learning_outcomes=("Outcome A",),
        ordered_rlo_refs=(ref_a, ref_b),
        sequencing_rationale="logical order",
        assessment_strategy="quiz at end",
        estimated_duration_minutes=30,
        source_rlo_versions={"rlo-1": "v1", "rlo-2": "v1"},
    )
