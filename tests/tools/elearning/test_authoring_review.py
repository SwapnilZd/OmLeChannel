"""Content-agnostic tests for the learner-facing publication boundary."""
import pytest

from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
)
from learning_pipeline.tools.elearning_bundle._authoring_client import (
    PublicationReviewResult,
    StructuredReviewResponse,
)
from learning_pipeline.tools.elearning_bundle._authoring_controller import (
    AuthoringAgentController,
    _SEMANTIC_BLOCKING_CODES,
)
from learning_pipeline.tools.elearning_bundle._authoring_review import (
    build_learner_review_projection,
    deterministic_review,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    AuthoringFinding,
    AuthoringState,
    AuthoringWorkspace,
    FindingOwner,
    FindingRepairability,
    FindingSeverity,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
)


def test_internal_design_rationale_is_flagged_without_domain_assumptions():
    draft = ElearningCourseAuthorDraft(
        draft_id="generic-boundary-case",
        title="Generic Subject",
        authored_screens=(
            AuthoredScreenDraft(
                screen_id="generic-sequence",
                screen_type="process_sequence",
                source_scene_ids=("scene-generic",),
                content={
                    "heading": "Use the groups to reconstruct the sequence",
                    "introduction": (
                        "Grouping the items reduces recall load without changing "
                        "the sequence."
                    ),
                    "steps": [
                        {"label": "Group one", "detail": "Complete the first items."},
                        {"label": "Group two", "detail": "Complete the remaining items."},
                    ],
                },
            ),
        ),
    )
    findings = deterministic_review(draft)
    assert len(findings) == 1
    assert findings[0].screen_id == "generic-sequence"
    assert findings[0].category == "possible_internal_rationale"
    assert "reduces recall load" in (findings[0].evidence or "")


def test_pedagogy_as_subject_is_not_deterministically_blocked():
    draft = ElearningCourseAuthorDraft(
        draft_id="pedagogy-subject",
        title="Instructional Design Foundations",
        authored_screens=(
            AuthoredScreenDraft(
                screen_id="scaffolding-definition",
                screen_type="callout_focus",
                source_scene_ids=("scene-scaffolding",),
                content={
                    "headline": "Scaffolding supports progressive independence",
                    "body": (
                        "In instructional design, scaffolding provides temporary "
                        "support that is removed as capability develops."
                    ),
                },
            ),
        ),
    )
    findings = deterministic_review(draft)
    assert findings
    assert all(finding.severity == FindingSeverity.WARNING for finding in findings)
    assert not any(
        finding.severity == FindingSeverity.BLOCKING for finding in findings
    )


def test_review_projection_contains_only_editable_learner_content():
    brief = ElearningAuthoringBrief(
        deliverable_id="course-1",
        source_plan_id="plan-1",
        resolved_context_uri="memory://context",
        resolved_context_sha256="a" * 64,
        screen_requirements=(
            AuthoredScreenRequirement(
                screen_id="screen-title",
                source_scene_ids=("scene-1",),
                screen_type="title",
                content_direction="Introduce the approved subject.",
            ),
            AuthoredScreenRequirement(
                screen_id="screen-check",
                source_scene_ids=("scene-1",),
                screen_type="knowledge_check",
                content_direction="Present the approved assessment.",
            ),
        ),
    )
    course = {
        "screens": [
            {
                "screen_id": "screen-title",
                "type": "title",
                "sequence": 1,
                "rlo_source_refs": ["scene-1"],
                "course_title": "Generic Course",
                "subtitle": "A concise introduction.",
                "hook": "What should you consider first?",
                "metadata": {"duration_minutes": 3},
            },
            {
                "screen_id": "screen-check",
                "type": "knowledge_check",
                "sequence": 2,
                "rlo_source_refs": ["scene-1"],
                "question_id": "source-question",
                "stem": "Source-controlled question",
                "question_type": "multiple_choice_single",
                "options": [],
            },
        ]
    }

    projection = build_learner_review_projection(course, brief)

    assert projection == (
        {
            "screen_id": "screen-title",
            "screen_type": "title",
            "learner_purpose": "Introduce the approved subject.",
            "learner_action": "consume",
            "editable_fields": ("course_title", "hook", "subtitle"),
            "learner_visible_content": {
                "course_title": "Generic Course",
                "hook": "What should you consider first?",
                "subtitle": "A concise introduction.",
            },
        },
    )


def test_semantic_blocking_policy_has_only_four_material_defects():
    assert _SEMANTIC_BLOCKING_CODES == {
        "SOURCE_FIDELITY",
        "REQUIRED_CONTENT_MISSING",
        "LEARNER_INSTRUCTION_UNUSABLE",
        "PEDAGOGICAL_RATIONALE_LEAKAGE",
    }


@pytest.mark.asyncio
async def test_semantic_reviewer_cannot_revise_source_controlled_knowledge_check():
    draft = ElearningCourseAuthorDraft(
        draft_id="assessment-draft",
        title="Generic Subject",
        authored_screens=(
            AuthoredScreenDraft(
                screen_id="check-1",
                screen_type="knowledge_check",
                source_scene_ids=("scene-1",),
                content={
                    "question_id": "q-1",
                    "stem": "Which option is correct?",
                    "question_type": "multiple_choice_single",
                    "options": [
                        {
                            "id": "a",
                            "text": "Correct",
                            "correct": True,
                            "feedback": "Correct.",
                        },
                        {
                            "id": "b",
                            "text": "Incorrect",
                            "correct": False,
                            "feedback": "Try again.",
                        },
                    ],
                    "questions": [
                        {
                            "question_id": "q-1",
                            "stem": "Which option is correct?",
                            "question_type": "multiple_choice_single",
                            "options": [
                                {
                                    "id": "a",
                                    "text": "Correct",
                                    "correct": True,
                                    "feedback": "Correct.",
                                },
                                {
                                    "id": "b",
                                    "text": "Incorrect",
                                    "correct": False,
                                    "feedback": "Try again.",
                                },
                            ],
                        }
                    ],
                },
            ),
        ),
    )

    class Tools:
        @staticmethod
        def review_publishability(_draft):
            return ()

    class Client:
        @staticmethod
        async def review(**_kwargs):
            return StructuredReviewResponse(
                result=PublicationReviewResult(
                    findings=(
                        AuthoringFinding(
                            finding_id="invalid-shape-request",
                            code="SEMANTIC_INTERACTION",
                            screen_id="check-1",
                            category="interaction",
                            severity=FindingSeverity.BLOCKING,
                            owner=FindingOwner.AUTHOR,
                            repairability=FindingRepairability.AUTHOR_PATCH,
                            field_path="content.questions",
                            message="Clear the mirrored top-level fields.",
                            evidence="The reviewer inspected an internal assessment field.",
                            revision_instruction="Use only questions.",
                        ),
                    )
                ),
                model="review-test",
            )

    controller = object.__new__(AuthoringAgentController)
    controller._tools = Tools()
    controller._client = Client()
    controller._policy = AgenticExecutionPolicy(
        max_model_calls=2, max_internal_tool_calls=2
    )
    workspace = AuthoringWorkspace(
        workflow_id="workflow-1",
        task_id="author-1",
        deliverable_id="course-1",
        input_hash="hash",
        prompt_version="test",
        state=AuthoringState.VALIDATED,
        required_screen_ids=("check-1",),
        draft=draft,
    )
    brief = ElearningAuthoringBrief(
        deliverable_id="course-1",
        source_plan_id="plan-1",
        resolved_context_uri="fake://context.json",
        resolved_context_sha256="a" * 64,
        screen_requirements=(
            AuthoredScreenRequirement(
                screen_id="check-1",
                source_scene_ids=("scene-1",),
                screen_type="knowledge_check",
                content_direction="Render the approved assessment.",
            ),
        ),
    )

    findings, updated = await controller._review(
        workspace=workspace,
        brief=brief,
        resolved_context={},
        course_dict={
            "screens": [
                {
                    "screen_id": "check-1",
                    "type": "knowledge_check",
                    "sequence": 1,
                    "rlo_source_refs": ["scene-1"],
                    "question_id": "q-1",
                    "stem": "Which option is correct?",
                    "question_type": "multiple_choice_single",
                    "options": [],
                }
            ]
        },
    )

    assert findings == ()
    assert updated.model_call_count == 0


def test_finding_records_stable_owner_and_repair_route():
    finding = AuthoringFinding(
        finding_id="copy-1",
        code="SOURCE_MEANING_CHANGED",
        screen_id="screen-1",
        category="source_fidelity",
        severity=FindingSeverity.BLOCKING,
        owner=FindingOwner.AUTHOR,
        repairability=FindingRepairability.AUTHOR_PATCH,
        field_path="content.body",
        message="The copy changes the approved meaning.",
        evidence="Approved source and visible copy differ.",
        revision_instruction="Restore the approved distinction.",
    )

    assert finding.model_dump(mode="json") == {
        "finding_id": "copy-1",
        "code": "SOURCE_MEANING_CHANGED",
        "screen_id": "screen-1",
        "category": "source_fidelity",
        "severity": "blocking",
        "owner": "author",
        "repairability": "author_patch",
        "field_path": "content.body",
        "message": "The copy changes the approved meaning.",
        "evidence": "Approved source and visible copy differ.",
        "revision_instruction": "Restore the approved distinction.",
    }


def test_author_blocker_requires_an_editable_field_path():
    with pytest.raises(ValueError, match="field_path"):
        AuthoringFinding(
            finding_id="copy-1",
            code="SOURCE_MEANING_CHANGED",
            screen_id="screen-1",
            category="source_fidelity",
            severity=FindingSeverity.BLOCKING,
            owner=FindingOwner.AUTHOR,
            repairability=FindingRepairability.AUTHOR_PATCH,
            message="The copy changes the approved meaning.",
            revision_instruction="Restore the approved distinction.",
        )


def test_author_blocker_requires_visible_or_source_evidence():
    with pytest.raises(ValueError, match="evidence"):
        AuthoringFinding(
            finding_id="copy-1",
            code="SOURCE_FIDELITY",
            screen_id="screen-1",
            category="source_fidelity",
            severity=FindingSeverity.BLOCKING,
            owner=FindingOwner.AUTHOR,
            repairability=FindingRepairability.AUTHOR_PATCH,
            field_path="content.body",
            message="The copy changes the approved meaning.",
            revision_instruction="Restore the approved distinction.",
        )
