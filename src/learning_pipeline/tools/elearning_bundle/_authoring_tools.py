"""Deterministic, scope-limited tools used by AuthoringAgentController."""
from __future__ import annotations

import json
from typing import Any

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    ElearningCourseAuthorDraft,
    _REQUIRED_CONTENT_FIELDS,
)
from learning_pipeline.tools.elearning_bundle._authoring_errors import (
    AuthoringPreflightError,
)
from learning_pipeline.tools.elearning_bundle._assessment_fidelity import (
    extract_assessment_ledger,
    hydrate_approved_assessments,
    validate_assessment_fidelity,
)
from learning_pipeline.tools.elearning_bundle._content_builder import (
    BuildError,
    ElearningCourseContentBuilder,
)
from learning_pipeline.tools.elearning_bundle._authoring_review import (
    deterministic_review_projection,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    AuthoringFinding,
    FindingOwner,
    FindingRepairability,
    FindingSeverity,
    ScreenIntent,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
    natural_learner_action,
    resolved_learner_action,
    SlotPreservationReport,
)


class AuthoringTools:
    def __init__(self, builder: ElearningCourseContentBuilder) -> None:
        self._builder = builder

    def inspect_assignment(
        self,
        brief: ElearningAuthoringBrief,
        resolved_context: dict[str, Any] | None = None,
    ) -> tuple[ScreenIntent, ...]:
        self._validate_assignment(brief, resolved_context)
        return tuple(
            ScreenIntent(
                screen_id=req.screen_id,
                screen_type=req.screen_type,
                learner_action=resolved_learner_action(req).value,
                source_scene_ids=req.source_scene_ids,
                learner_purpose=req.content_direction,
                internal_only_notes=(
                    "Treat production direction and pedagogical rationale as internal.",
                    "Publish only grounded subject matter and learner instructions.",
                ),
            )
            for req in brief.screen_requirements
            if isinstance(req, AuthoredScreenRequirement)
        )

    @staticmethod
    def _validate_assignment(
        brief: ElearningAuthoringBrief,
        resolved_context: dict[str, Any] | None,
    ) -> None:
        authored = tuple(
            requirement
            for requirement in brief.screen_requirements
            if isinstance(requirement, AuthoredScreenRequirement)
        )
        for requirement in authored:
            action = resolved_learner_action(requirement)
            supported = natural_learner_action(requirement.screen_type)
            if action != supported:
                raise AuthoringPreflightError(
                    "PREFLIGHT_UNSUPPORTED_LEARNER_ACTION",
                    requirement.screen_id,
                    f"Requests learner action "
                    f"{action.value!r}, but {requirement.screen_type!r} supports "
                    f"{supported.value!r}.",
                )

        if resolved_context is not None:
            assessment_ledger = extract_assessment_ledger(resolved_context)
            for requirement in authored:
                if (
                    requirement.screen_type == "knowledge_check"
                    and not any(
                        assessment_ledger.get(scene_id)
                        for scene_id in requirement.source_scene_ids
                    )
                ):
                    raise AuthoringPreflightError(
                        "PREFLIGHT_ASSESSMENT_SOURCE_MISSING",
                        requirement.screen_id,
                        "A knowledge_check requires an approved multiple-choice "
                        "assessment in its assigned source scenes.",
                    )

        next_resolution_id: str | None = None
        for requirement in reversed(authored):
            if requirement.screen_type == "scenario_resolution":
                next_resolution_id = requirement.screen_id
            elif requirement.screen_type == "scenario_branch":
                if next_resolution_id is None:
                    raise AuthoringPreflightError(
                        "PREFLIGHT_SCENARIO_GRAPH_INVALID",
                        requirement.screen_id,
                        "Requires a following scenario_resolution before the "
                        "next scenario setup.",
                    )
            elif requirement.screen_type == "scenario_setup":
                next_resolution_id = None

    def inspect_context(self, context_bytes: bytes) -> dict[str, Any]:
        try:
            value = json.loads(context_bytes)
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {"content": value}

    def inspect_schemas(
        self, brief: ElearningAuthoringBrief
    ) -> dict[str, tuple[str, ...]]:
        return {
            req.screen_id: tuple(sorted(_REQUIRED_CONTENT_FIELDS[req.screen_type]))
            for req in brief.screen_requirements
            if isinstance(req, AuthoredScreenRequirement)
        }

    def validate_draft(
        self,
        brief: ElearningAuthoringBrief,
        draft: ElearningCourseAuthorDraft,
        resolved_context: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, SlotPreservationReport | None, tuple[AuthoringFinding, ...]]:
        try:
            course, report = self._builder.build(brief, draft)
            findings = validate_assessment_fidelity(
                brief, draft.authored_screens, resolved_context
            )
            return course, report, findings
        except BuildError as exc:
            screen_id = exc.screen_id or "__course__"
            return None, None, (
                AuthoringFinding(
                    finding_id=f"deterministic-validation-{screen_id}",
                    code="COURSE_BUILD_VALIDATION_FAILED",
                    screen_id=screen_id,
                    category="validation",
                    severity=FindingSeverity.BLOCKING,
                    owner=FindingOwner.BUILDER,
                    repairability=FindingRepairability.AUTOMATIC,
                    message=str(exc),
                    revision_instruction=(
                        "Correct the draft while preserving the required screen contract."
                    ),
                ),
            )
        except Exception as exc:
            return None, None, (
                AuthoringFinding(
                    finding_id="deterministic-validation-__course__",
                    code="COURSE_BUILD_VALIDATION_FAILED",
                    screen_id="__course__",
                    category="validation",
                    severity=FindingSeverity.BLOCKING,
                    owner=FindingOwner.BUILDER,
                    repairability=FindingRepairability.AUTOMATIC,
                    message=str(exc),
                    revision_instruction=(
                        "Correct the draft while preserving the required screen contract."
                    ),
                ),
            )

    def hydrate_assessments(
        self,
        brief: ElearningAuthoringBrief,
        draft: ElearningCourseAuthorDraft,
        resolved_context: dict[str, Any],
    ) -> ElearningCourseAuthorDraft:
        return hydrate_approved_assessments(brief, draft, resolved_context)

    def hydrate_scenario_navigation(
        self,
        brief: ElearningAuthoringBrief,
        draft: ElearningCourseAuthorDraft,
    ) -> ElearningCourseAuthorDraft:
        """Set branch continuation links from the immutable screen sequence.

        Navigation is production structure, not authored instructional content.
        Every branch in a scenario deterministically continues to the next
        scenario-resolution requirement, regardless of the model's placeholder.
        """

        targets: dict[str, str] = {}
        next_resolution_id: str | None = None
        for requirement in reversed(brief.screen_requirements):
            if not isinstance(requirement, AuthoredScreenRequirement):
                continue
            if requirement.screen_type == "scenario_resolution":
                next_resolution_id = requirement.screen_id
            elif requirement.screen_type == "scenario_branch" and next_resolution_id:
                targets[requirement.screen_id] = next_resolution_id
            elif requirement.screen_type == "scenario_setup":
                next_resolution_id = None

        changed = False
        screens = []
        for screen in draft.authored_screens:
            target = targets.get(screen.screen_id)
            if target and screen.content.resolution_screen_id != target:
                screen = screen.model_copy(
                    update={
                        "content": screen.content.model_copy(
                            update={"resolution_screen_id": target}
                        )
                    }
                )
                changed = True
            screens.append(screen)
        if not changed:
            return draft
        return draft.model_copy(update={"authored_screens": tuple(screens)})

    def review_publishability(
        self, learner_projection: tuple[dict[str, Any], ...]
    ) -> tuple[AuthoringFinding, ...]:
        return deterministic_review_projection(learner_projection)
