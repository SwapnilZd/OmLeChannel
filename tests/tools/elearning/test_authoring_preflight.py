"""Topic-neutral tests for deterministic authoring-assignment preflight."""

import pytest

from learning_pipeline.tools.elearning_bundle._authoring_tools import AuthoringTools
from learning_pipeline.tools.elearning_bundle._content_builder import (
    ElearningCourseContentBuilder,
)
from learning_pipeline.tools.elearning_bundle._authoring_errors import (
    AuthoringPreflightError,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
    LearnerAction,
)


def _brief(*requirements: AuthoredScreenRequirement) -> ElearningAuthoringBrief:
    return ElearningAuthoringBrief(
        deliverable_id="generic-course",
        source_plan_id="generic-plan",
        resolved_context_uri="memory://generic-context",
        resolved_context_sha256="a" * 64,
        screen_requirements=requirements,
    )


def _requirement(
    screen_id: str,
    screen_type: str,
    learner_action: LearnerAction | None,
) -> AuthoredScreenRequirement:
    return AuthoredScreenRequirement(
        screen_id=screen_id,
        screen_type=screen_type,
        source_scene_ids=("scene-1",),
        content_direction="Teach the assigned source content.",
        learner_action=learner_action,
    )


def test_preflight_rejects_action_the_component_cannot_support():
    brief = _brief(
        _requirement("screen-static", "structured_list", LearnerAction.CHOOSE)
    )

    with pytest.raises(
        AuthoringPreflightError, match="PREFLIGHT_UNSUPPORTED_LEARNER_ACTION"
    ) as error:
        AuthoringTools(ElearningCourseContentBuilder()).inspect_assignment(brief)

    assert error.value.screen_id == "screen-static"
    assert error.value.owner == "planner"


def test_preflight_requires_scenario_branch_to_have_a_resolution():
    brief = _brief(
        _requirement("screen-setup", "scenario_setup", LearnerAction.CHOOSE),
        _requirement("screen-branch", "scenario_branch", LearnerAction.CONSUME),
    )

    with pytest.raises(
        AuthoringPreflightError, match="PREFLIGHT_SCENARIO_GRAPH_INVALID"
    ):
        AuthoringTools(ElearningCourseContentBuilder()).inspect_assignment(brief)


def test_preflight_compiles_supported_actions_and_scenario_graph():
    brief = _brief(
        _requirement("screen-setup", "scenario_setup", LearnerAction.CHOOSE),
        _requirement("screen-branch", "scenario_branch", LearnerAction.CONSUME),
        _requirement("screen-resolution", "scenario_resolution", LearnerAction.CONSUME),
    )

    intents = AuthoringTools(ElearningCourseContentBuilder()).inspect_assignment(brief)

    assert [intent.learner_action for intent in intents] == [
        "choose",
        "consume",
        "consume",
    ]


def test_preflight_derives_action_for_compatible_older_brief():
    requirement = AuthoredScreenRequirement(
        screen_id="screen-legacy",
        screen_type="disclosure_list",
        source_scene_ids=("scene-1",),
        content_direction="Present the assigned source content.",
    )

    intents = AuthoringTools(ElearningCourseContentBuilder()).inspect_assignment(
        _brief(requirement)
    )

    assert intents[0].learner_action == "reveal"


def test_preflight_rejects_new_knowledge_check_without_approved_assessment():
    brief = _brief(
        _requirement("screen-check", "knowledge_check", LearnerAction.CHOOSE)
    )

    with pytest.raises(
        AuthoringPreflightError, match="PREFLIGHT_ASSESSMENT_SOURCE_MISSING"
    ):
        AuthoringTools(ElearningCourseContentBuilder()).inspect_assignment(
            brief, resolved_context={"scenes": []}
        )
