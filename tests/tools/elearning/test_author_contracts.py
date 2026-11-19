"""Tests for Phase 14B authoring contracts.

Covers: GeneratedAssetRequest, AuthoredScreenDraft, ElearningCourseAuthorDraft,
AgenticExecutionPolicy, ElearningAuthoringTrace, _assert_no_unsafe_content.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AUTHORABLE_SCREEN_TYPES,
    RESERVED_SCREEN_TYPES,
    AgenticExecutionPolicy,
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
    ElearningAuthoringTrace,
    GeneratedAssetRequest,
    _REQUIRED_CONTENT_FIELDS,
    _assert_no_unsafe_content,
)
from learning_pipeline.tools.elearning_bundle.contracts import SlotPreservationReport


# ── _assert_no_unsafe_content ─────────────────────────────────────────────────


def test_safe_content_passes():
    _assert_no_unsafe_content({"heading": "Independence Threats", "items": ["a", "b"]})


def test_script_tag_fails():
    with pytest.raises(ValueError, match="Unsafe content"):
        _assert_no_unsafe_content("<script>alert(1)</script>", "field")


def test_javascript_uri_fails():
    with pytest.raises(ValueError, match="Unsafe content"):
        _assert_no_unsafe_content("javascript:void(0)", "link")


def test_event_handler_fails():
    with pytest.raises(ValueError, match="Unsafe content"):
        _assert_no_unsafe_content("onclick=doEvil()", "attr")


def test_iframe_fails():
    with pytest.raises(ValueError, match="Unsafe content"):
        _assert_no_unsafe_content("<iframe src='bad'>", "html")


def test_nested_unsafe_in_dict_fails():
    with pytest.raises(ValueError, match="Unsafe content"):
        _assert_no_unsafe_content({"safe": "ok", "bad": "<script>x</script>"})


def test_nested_unsafe_in_list_fails():
    with pytest.raises(ValueError, match="Unsafe content"):
        _assert_no_unsafe_content(["ok", "also ok", "javascript:evil()"])


# ── AuthoredScreenDraft ───────────────────────────────────────────────────────


def test_authored_screen_draft_valid():
    draft = AuthoredScreenDraft(
        screen_id="screen-title",
        screen_type="title",
        source_scene_ids=("scene-01",),
        content={"course_title": "Ethics", "subtitle": "A primer", "hook": "...", "metadata": {}},
    )
    assert draft.screen_type == "title"


def test_authored_screen_draft_video_slot_type_fails():
    with pytest.raises(ValidationError, match="reserved"):
        AuthoredScreenDraft(
            screen_id="bad",
            screen_type="video_slot",
            source_scene_ids=("scene-01",),
            content={},
        )


def test_authored_screen_draft_video_player_type_fails():
    with pytest.raises(ValidationError, match="reserved"):
        AuthoredScreenDraft(
            screen_id="bad",
            screen_type="video_player",
            source_scene_ids=("scene-01",),
            content={},
        )


def test_authored_screen_draft_unknown_type_fails():
    with pytest.raises(ValidationError, match="Unknown screen_type"):
        AuthoredScreenDraft(
            screen_id="bad",
            screen_type="nonexistent_type",
            source_scene_ids=("scene-01",),
            content={},
        )


def test_authored_screen_draft_unsafe_content_fails():
    with pytest.raises(ValidationError, match="Unsafe content"):
        AuthoredScreenDraft(
            screen_id="bad",
            screen_type="key_takeaways",
            source_scene_ids=("scene-01",),
            content={"heading": "<script>alert(1)</script>"},
        )


def test_authored_screen_draft_blank_screen_id_fails():
    with pytest.raises(ValidationError):
        AuthoredScreenDraft(
            screen_id="",
            screen_type="title",
            source_scene_ids=("scene-01",),
            content={},
        )


# ── ElearningCourseAuthorDraft ────────────────────────────────────────────────


def _make_title_draft(screen_id: str = "screen-title") -> AuthoredScreenDraft:
    return AuthoredScreenDraft(
        screen_id=screen_id,
        screen_type="title",
        source_scene_ids=("scene-01",),
        content={
            "course_title": "Ethics in Practice",
            "subtitle": "A primer for professionals.",
            "hook": "How should you respond when faced with a conflict of interest?",
        },
    )


def test_elearning_course_author_draft_valid():
    draft = ElearningCourseAuthorDraft(
        draft_id="draft-001",
        title="Test Course",
        authored_screens=(_make_title_draft(),),
    )
    assert draft.draft_id == "draft-001"
    assert len(draft.authored_screens) == 1


def test_elearning_course_author_draft_duplicate_screen_ids_fails():
    with pytest.raises(ValidationError, match="unique screen_ids"):
        ElearningCourseAuthorDraft(
            draft_id="draft-001",
            title="Test",
            authored_screens=(
                _make_title_draft("same-id"),
                _make_title_draft("same-id"),
            ),
        )


def test_elearning_course_author_draft_blank_draft_id_fails():
    with pytest.raises(ValidationError):
        ElearningCourseAuthorDraft(
            draft_id="",
            title="Test",
            authored_screens=(),
        )


def test_elearning_course_author_draft_empty_screens_allowed():
    # Zero authored screens is valid (e.g. a video-only course)
    draft = ElearningCourseAuthorDraft(
        draft_id="draft-001",
        title="Video-Only Course",
        authored_screens=(),
    )
    assert len(draft.authored_screens) == 0


# ── AgenticExecutionPolicy ────────────────────────────────────────────────────


def test_default_policy_values():
    policy = AgenticExecutionPolicy()
    assert policy.max_model_calls == 3
    assert policy.max_fitting_attempts == 2
    assert policy.max_repair_attempts == 2
    assert policy.timeout_seconds == 120
    assert policy.max_cost_usd is None


def test_policy_rejects_zero_model_calls():
    with pytest.raises(ValidationError):
        AgenticExecutionPolicy(max_model_calls=0)


def test_policy_rejects_short_timeout():
    with pytest.raises(ValidationError):
        AgenticExecutionPolicy(timeout_seconds=5)


def test_policy_with_cost_ceiling():
    policy = AgenticExecutionPolicy(max_cost_usd=2.50)
    assert policy.max_cost_usd == 2.50


# ── ElearningAuthoringTrace ───────────────────────────────────────────────────


def _make_report() -> SlotPreservationReport:
    return SlotPreservationReport.build(
        required=("intro-video",),
        discovered=["intro-video"],
    )


def test_authoring_trace_valid():
    trace = ElearningAuthoringTrace(
        workflow_id="wf-001",
        task_id="author-1",
        brief_hash="abc123",
        context_hash="def456",
        prompt_version="course_author_v1",
        model="gpt-5.6",
        model_call_count=1,
        internal_tool_call_count=0,
        fitting_attempt_count=1,
        repair_attempt_count=0,
        authored_screen_ids=("screen-title", "screen-objectives"),
        selected_screen_types={"screen-title": "title", "screen-objectives": "objectives"},
        slot_report=_make_report(),
    )
    assert trace.model_call_count == 1
    assert trace.slot_report.valid is True


def test_authoring_trace_immutable():
    trace = ElearningAuthoringTrace(
        workflow_id="wf-001",
        task_id="t1",
        brief_hash="h1",
        context_hash="h2",
        prompt_version="v1",
        model="gpt-5.6",
        model_call_count=1,
        internal_tool_call_count=0,
        fitting_attempt_count=1,
        repair_attempt_count=0,
        authored_screen_ids=(),
        selected_screen_types={},
        slot_report=_make_report(),
    )
    with pytest.raises(Exception):  # FrozenModel raises on assignment
        trace.model_call_count = 5


# ── Screen type constants ─────────────────────────────────────────────────────


def test_reserved_types_not_in_authorable():
    assert not (RESERVED_SCREEN_TYPES & AUTHORABLE_SCREEN_TYPES)


def test_authorable_types_known():
    assert "title" in AUTHORABLE_SCREEN_TYPES
    assert "objectives" in AUTHORABLE_SCREEN_TYPES
    assert "knowledge_check" in AUTHORABLE_SCREEN_TYPES
    assert "completion" in AUTHORABLE_SCREEN_TYPES


def test_reserved_includes_video_slot_and_video_player():
    assert "video_slot" in RESERVED_SCREEN_TYPES
    assert "video_player" in RESERVED_SCREEN_TYPES


def test_knowledge_check_rejects_open_response():
    content = dict(_MINIMAL_VALID_CONTENT["knowledge_check"])
    content["question_type"] = "open_response"
    with pytest.raises(ValidationError):
        AuthoredScreenDraft(
            screen_id="screen-check",
            screen_type="knowledge_check",
            source_scene_ids=("scene-1",),
            content=content,
        )


def test_knowledge_check_requires_at_least_two_options():
    content = dict(_MINIMAL_VALID_CONTENT["knowledge_check"])
    content["options"] = content["options"][:1]
    with pytest.raises(ValidationError, match="between 2 and 5 options"):
        AuthoredScreenDraft(
            screen_id="screen-check",
            screen_type="knowledge_check",
            source_scene_ids=("scene-1",),
            content=content,
        )


# ── Per-type required content field validation ────────────────────────────────
# Minimal valid content for every authorable screen type.
# Used both for positive and negative (missing-field) tests.

_MINIMAL_VALID_CONTENT: dict[str, dict] = {
    "title": {
        "course_title": "Test Course",
        "subtitle": "A one-sentence description.",
        "hook": "What would you do?",
    },
    "objectives": {
        "heading": "Learning Objectives",
        "objectives": ["Apply the framework."],
    },
    "concept_flip_card": {
        "section_label": "Key Concepts",
        "instruction": "Flip each card to reveal the definition.",
        "cards": [
            {
                "id": "c1",
                "front_label": "Term A",
                "front_teaser": "A foundational idea.",
                "back_definition": "The full definition.",
                "back_examples": ["Example 1"],
                "back_safeguard": "Watch out for this.",
            }
        ],
    },
    "worked_example": {
        "title": "Worked Example Title",
        "scenario": "A manager faces a dilemma.",
        "analysis": "The situation involves competing interests.",
        "resolution": "She disclosed the conflict.",
        "lesson": "Early disclosure prevents escalation.",
    },
    "contrast_example": {
        "title": "Contrast Example",
        "acceptable": {"label": "Good", "description": "Discloses early.", "reason": "Transparency."},
        "unacceptable": {"label": "Bad", "description": "Hides the issue.", "reason": "Concealment."},
    },
    "scenario_setup": {
        "title": "Scenario Setup",
        "setup_text": "You are reviewing a vendor contract.",
        "prompt": "What do you do?",
        "branches": [{"id": "choice-a", "label": "Disclose the relationship"}],
    },
    "scenario_branch": {
        "branch_id": "choice-a",
        "outcome_type": "correct",
        "feedback_title": "Good Choice",
        "feedback_body": "You made the right call by disclosing.",
        "resolution_screen_id": "screen-scenario-resolution",
    },
    "scenario_resolution": {
        "title": "Resolution",
        "body": "Disclosing conflicts protects everyone.",
    },
    "knowledge_check": {
        "question_id": "kc-001",
        "stem": "Which action is correct?",
        "question_type": "multiple_choice_single",
        "options": [
            {"id": "a", "text": "Disclose", "correct": True, "feedback": "Correct."},
            {"id": "b", "text": "Ignore", "correct": False, "feedback": "Incorrect."},
        ],
    },
    "completion": {
        "heading": "Module Complete",
        "message": "Congratulations.",
        "skills_reinforced": ["Ethical decision-making"],
    },
    "process_sequence": {
        "heading": "The Process",
        "introduction": "Follow these steps.",
        "steps": [{"label": "Step 1", "detail": "Do this first."}],
    },
    "misconception_buster": {
        "heading": "Common Misconceptions",
        "pairs": [{"claim": "It's fine.", "correction": "It's not fine."}],
    },
    "comparison_table": {
        "heading": "Comparison",
        "columns": ["Aspect", "Option A", "Option B"],
        "rows": [{"label": "Speed", "values": ["Fast", "Slow"]}],
    },
    "tabbed_content": {
        "heading": "Key Topics",
        "instruction": "Select a tab to learn more.",
        "tabs": [{"label": "Topic 1", "heading": "Topic One", "body": "Details here."}],
    },
    "rule_card": {
        "heading": "The Rule",
        "principle": "Always disclose.",
        "supporting_detail": "Disclosure protects all parties.",
        "examples": ["Disclose vendor relationships."],
    },
    "reflection_prompt": {
        "heading": "Reflect",
        "prompt": "What would you do differently?",
        "guidance": "Think about your past decisions.",
    },
    "key_takeaways": {
        "heading": "Key Takeaways",
        "takeaways": ["Disclose early.", "Document everything."],
    },
    "card_grid": {
        "heading": "Core Concepts",
        "cards": [{"eyebrow": "Concept", "heading": "Card 1", "body": "Summary.", "icon": None}],
    },
    "callout_focus": {
        "headline": "Important Principle",
        "body": "This is the key point.",
    },
    "structured_list": {
        "heading": "Key Points",
        "items": [{"label": "Point 1", "detail": "This matters."}],
    },
    "paired_comparison": {
        "heading": "Comparison",
        "left": {"label": "Option A", "summary": "Fast", "points": ["Pro 1"]},
        "right": {"label": "Option B", "summary": "Reliable", "points": ["Pro 2"]},
    },
    "disclosure_list": {
        "heading": "Disclosure Items",
        "instruction": "Click each item to expand.",
        "items": [{"label": "Item 1", "body": "Details."}],
    },
    "relationship_diagram": {
        "heading": "Relationships",
        "nodes": [{"id": "n1", "label": "Node 1"}],
    },
}


@pytest.mark.parametrize("screen_type", sorted(_MINIMAL_VALID_CONTENT))
def test_minimal_valid_content_passes_for_each_screen_type(screen_type):
    """Minimally valid content passes parse-time validation for every authorable screen type."""
    draft = AuthoredScreenDraft(
        screen_id=f"screen-{screen_type}",
        screen_type=screen_type,
        source_scene_ids=("scene-01",),
        content=_MINIMAL_VALID_CONTENT[screen_type],
    )
    assert draft.screen_type == screen_type


@pytest.mark.parametrize("screen_type,required_field", [
    (st, f)
    for st, fields in sorted(_REQUIRED_CONTENT_FIELDS.items())
    for f in sorted(fields)
])
def test_omitting_required_content_field_fails(screen_type, required_field):
    """Omitting any required content field raises ValidationError at parse time."""
    base = dict(_MINIMAL_VALID_CONTENT[screen_type])
    # Remove the field under test.  For concept_flip_card.section_label we also
    # remove the heading alias so the normalization path doesn't rescue it.
    base.pop(required_field, None)
    # Remove section_label alias for heading tests so normalization cannot compensate.
    if required_field == "heading":
        base.pop("section_label", None)

    with pytest.raises(ValidationError, match="missing required content fields"):
        AuthoredScreenDraft(
            screen_id=f"screen-{screen_type}",
            screen_type=screen_type,
            source_scene_ids=("scene-01",),
            content=base,
        )


# ── scenario_branch regression tests ─────────────────────────────────────────


def test_scenario_branch_with_wrong_field_set_fails_at_parse_time():
    """Regression: scenario_branch with 'instruction' (wrong field) raises at parse, not in builder."""
    with pytest.raises(ValidationError, match="missing required content fields"):
        AuthoredScreenDraft(
            screen_id="s-branch",
            screen_type="scenario_branch",
            source_scene_ids=("scene-01",),
            content={"instruction": "Review the scenario before choosing."},
        )


def test_scenario_branch_all_required_fields_accepted():
    draft = AuthoredScreenDraft(
        screen_id="s-branch",
        screen_type="scenario_branch",
        source_scene_ids=("scene-01",),
        content={
            "branch_id": "choice-a",
            "outcome_type": "correct",
            "feedback_title": "Good Choice",
            "feedback_body": "You disclosed the relationship promptly.",
            "resolution_screen_id": "s-scenario-resolution",
        },
    )
    assert draft.content.branch_id == "choice-a"
    assert draft.content.outcome_type == "correct"
    assert draft.content.resolution_screen_id == "s-scenario-resolution"


def test_scenario_branch_missing_branch_id_fails():
    with pytest.raises(ValidationError, match="missing required content fields"):
        AuthoredScreenDraft(
            screen_id="s-branch",
            screen_type="scenario_branch",
            source_scene_ids=("scene-01",),
            content={
                "outcome_type": "correct",
                "feedback_title": "Good Choice",
                "feedback_body": "You did the right thing.",
                "resolution_screen_id": "s-scenario-resolution",
            },
        )


def test_scenario_branch_missing_resolution_screen_id_fails():
    with pytest.raises(ValidationError, match="missing required content fields"):
        AuthoredScreenDraft(
            screen_id="s-branch",
            screen_type="scenario_branch",
            source_scene_ids=("scene-01",),
            content={
                "branch_id": "choice-a",
                "outcome_type": "correct",
                "feedback_title": "Good Choice",
                "feedback_body": "You did the right thing.",
                # resolution_screen_id intentionally omitted
            },
        )


# ── section_label alias acceptance ───────────────────────────────────────────


def test_process_sequence_accepts_section_label_as_heading_alias():
    """process_sequence accepts section_label in place of heading (builder normalization alias)."""
    draft = AuthoredScreenDraft(
        screen_id="s-seq",
        screen_type="process_sequence",
        source_scene_ids=("scene-01",),
        content={
            "section_label": "The Process",  # alias for heading
            "introduction": "Follow these steps.",
            "steps": [{"label": "Step 1", "detail": "First action."}],
        },
    )
    assert draft.screen_type == "process_sequence"


def test_concept_flip_card_requires_section_label_not_heading():
    """concept_flip_card must use section_label, not heading."""
    # heading instead of section_label → missing section_label
    with pytest.raises(ValidationError, match="missing required content fields"):
        AuthoredScreenDraft(
            screen_id="s-flip",
            screen_type="concept_flip_card",
            source_scene_ids=("scene-01",),
            content={
                "heading": "Key Concepts",  # wrong field for concept_flip_card
                "instruction": "Flip each card.",
                "cards": [
                    {
                        "id": "c1",
                        "front_label": "A",
                        "front_teaser": "B",
                        "back_definition": "C",
                        "back_examples": ["D"],
                        "back_safeguard": "E",
                    }
                ],
            },
        )


def test_knowledge_check_accepts_questions_only_until_source_hydration():
    draft = AuthoredScreenDraft.model_validate(
        {
            "screen_id": "screen-check",
            "screen_type": "knowledge_check",
            "source_scene_ids": ["scene-check"],
            "content": {
                "questions": [
                    {
                        "question_id": "q-1",
                        "stem": "Which option is correct?",
                        "question_type": "multiple_choice_single",
                        "options": [
                            {
                                "id": "a",
                                "text": "First",
                                "correct": True,
                                "feedback": "Correct.",
                            },
                            {
                                "id": "b",
                                "text": "Second",
                                "correct": False,
                                "feedback": "Try again.",
                            },
                        ],
                    }
                ]
            },
        }
    )

    assert draft.content.question_id is None
    assert draft.content.questions is not None


def test_relationship_diagram_rejects_descriptive_position_text():
    with pytest.raises(ValidationError, match="position"):
        AuthoredScreenDraft(
            screen_id="screen-relationship",
            screen_type="relationship_diagram",
            source_scene_ids=("scene-relationship",),
            content={
                "heading": "How the concepts connect",
                "nodes": [
                    {
                        "id": "node-1",
                        "label": "Vision",
                        "detail": "Sets direction.",
                        "position": "Start of the direction-to-execution sequence",
                    }
                ],
            },
        )
