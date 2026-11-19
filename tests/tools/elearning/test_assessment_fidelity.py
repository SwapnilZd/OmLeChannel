"""Content-agnostic exact-copy tests for approved assessment material."""
import pytest

from learning_pipeline.tools.elearning_bundle._assessment_fidelity import (
    extract_assessment_ledger,
    hydrate_approved_assessments,
    normalize_knowledge_check_requirements,
    validate_assessment_fidelity,
)
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
)


def _resolved_context(*, scene_id: str = "scene-assessment") -> dict:
    return {
        "scenes": [
            {
                "scene_id": scene_id,
                "content_items": [
                    {
                        "rlo_id": "rlo-generic",
                        "rlo_version": "1.0",
                        "content_type": "assessment_item",
                        "content_id": "assessment-1",
                        "title": "Choose the approved response.",
                        "content": (
                            "Assessment (multiple_choice_single): Choose the approved response.\n"
                            "Options:\n"
                            "  [CORRECT] (option-a) Approved response\n"
                            "    Feedback: Correct feedback.\n"
                            "  (option-b) Unapproved response\n"
                            "    Feedback: Corrective feedback."
                        ),
                        "source_refs": [],
                    }
                ],
            }
        ]
    }


def _brief(*, scene_id: str = "scene-assessment") -> ElearningAuthoringBrief:
    return ElearningAuthoringBrief(
        deliverable_id="generic-course",
        source_plan_id="generic-plan",
        resolved_context_uri="fake://context",
        resolved_context_sha256="a" * 64,
        screen_requirements=(
            AuthoredScreenRequirement(
                screen_id="knowledge-check",
                screen_type="knowledge_check",
                source_scene_ids=(scene_id,),
                content_direction="Present the approved assessment.",
            ),
        ),
    )


def _screen(
    *,
    question_id: str = "assessment-1",
    stem: str = "Choose the approved response.",
    question_type: str = "multiple_choice_single",
    first_text: str = "Approved response",
    first_correct: bool = True,
    first_feedback: str = "Correct feedback.",
    reverse_options: bool = False,
) -> AuthoredScreenDraft:
    options = [
        {
            "id": "option-a",
            "text": first_text,
            "correct": first_correct,
            "feedback": first_feedback,
        },
        {
            "id": "option-b",
            "text": "Unapproved response",
            "correct": False,
            "feedback": "Corrective feedback.",
        },
    ]
    if reverse_options:
        options.reverse()
    return AuthoredScreenDraft(
        screen_id="knowledge-check",
        screen_type="knowledge_check",
        source_scene_ids=("scene-assessment",),
        content={
            "question_id": question_id,
            "stem": stem,
            "question_type": question_type,
            "options": options,
        },
    )


def test_extracts_exact_assessment_ledger_from_resolved_context():
    ledger = extract_assessment_ledger(_resolved_context())
    approved = ledger["scene-assessment"][0]
    assert approved.assessment_id == "assessment-1"
    assert approved.stem == "Choose the approved response."
    assert approved.options[0].correct is True
    assert approved.options[1].feedback == "Corrective feedback."


def test_normalizes_repository_multiple_choice_type_to_single_select():
    context = _resolved_context()
    context["scenes"][0]["content_items"][0]["content"] = context["scenes"][0][
        "content_items"
    ][0]["content"].replace("multiple_choice_single", "multiple_choice")

    approved = extract_assessment_ledger(context)["scene-assessment"][0]

    assert approved.question_type == "multiple_choice_single"


def test_exact_assessment_passes():
    findings = validate_assessment_fidelity(
        _brief(), (_screen(),), _resolved_context()
    )
    assert findings == ()


def test_hydrates_exact_source_data_without_model_repair():
    mutated = _screen(
        stem="Paraphrased question.",
        first_text="Paraphrased option",
        first_feedback="Generic feedback.",
        reverse_options=True,
    )
    draft = ElearningCourseAuthorDraft(
        draft_id="generic-draft",
        title="Generic course",
        authored_screens=(mutated,),
    )

    hydrated = hydrate_approved_assessments(
        _brief(), draft, _resolved_context()
    )

    hydrated_screen = hydrated.authored_screens[0]
    assert hydrated_screen.content.question_id == "assessment-1"
    assert hydrated_screen.content.stem == "Choose the approved response."
    assert hydrated_screen.content.options == _screen().content.options
    assert hydrated_screen.content.questions is not None
    assert len(hydrated_screen.content.questions) == 1
    assert validate_assessment_fidelity(
        _brief(), hydrated.authored_screens, _resolved_context()
    ) == ()


def test_hydrates_every_assigned_assessment_into_ordered_group():
    context = _resolved_context()
    second = dict(context["scenes"][0]["content_items"][0])
    second["content_id"] = "assessment-2"
    second["content"] = second["content"].replace(
        "Choose the approved response.", "Choose the second approved response."
    ).replace("(option-a)", "(option-c)").replace("(option-b)", "(option-d)")
    context["scenes"][0]["content_items"].append(second)
    draft = ElearningCourseAuthorDraft(
        draft_id="grouped-draft",
        title="Generic course",
        authored_screens=(_screen(),),
    )

    hydrated = hydrate_approved_assessments(_brief(), draft, context)

    questions = hydrated.authored_screens[0].content.questions
    assert questions is not None
    assert [question.question_id for question in questions] == [
        "assessment-1",
        "assessment-2",
    ]
    assert validate_assessment_fidelity(
        _brief(), hydrated.authored_screens, context
    ) == ()


def test_check_without_approved_assessment_becomes_key_takeaways():
    brief = normalize_knowledge_check_requirements(_brief(), {"scenes": []})

    requirement = brief.screen_requirements[0]
    assert requirement.screen_id == "knowledge-check"
    assert requirement.source_scene_ids == ("scene-assessment",)
    assert requirement.screen_type == "key_takeaways"
    assert "rather than an assessment" in requirement.content_direction


def test_check_with_approved_assessment_remains_multiple_choice():
    brief = normalize_knowledge_check_requirements(_brief(), _resolved_context())

    assert brief.screen_requirements[0].screen_type == "knowledge_check"


@pytest.mark.parametrize(
    "change",
    [
        {"question_id": "invented-id"},
        {"stem": "Paraphrased question."},
        {"question_type": "multiple_choice_multi"},
        {"first_text": "Paraphrased option"},
        {"first_feedback": "Generic feedback."},
        {"reverse_options": True},
    ],
)
def test_any_assessment_mutation_is_blocking(change):
    findings = validate_assessment_fidelity(
        _brief(), (_screen(**change),), _resolved_context()
    )
    assert len(findings) == 1
    assert findings[0].category == "assessment_fidelity"
    assert findings[0].severity.value == "blocking"


def test_assessment_from_unassigned_scene_is_not_applied():
    findings = validate_assessment_fidelity(
        _brief(scene_id="different-scene"),
        (_screen(),),
        _resolved_context(scene_id="scene-assessment"),
    )
    assert findings == ()


def test_generated_formative_check_without_source_assessment_is_allowed():
    findings = validate_assessment_fidelity(
        _brief(), (_screen(),), {"scenes": []}
    )
    assert findings == ()


def test_unparseable_assigned_assessment_fails_closed():
    context = _resolved_context()
    context["scenes"][0]["content_items"][0]["content"] = "malformed source"
    findings = validate_assessment_fidelity(_brief(), (_screen(),), context)
    assert len(findings) == 1
    assert findings[0].category == "assessment_source_invalid"
    assert findings[0].severity.value == "blocking"
