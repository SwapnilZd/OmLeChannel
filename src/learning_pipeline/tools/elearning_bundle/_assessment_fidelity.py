"""Exact-copy validation for approved assessment content in resolved context."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    AuthoredScreenDraft,
    ElearningCourseAuthorDraft,
    KnowledgeCheckChoice,
    KnowledgeCheckQuestion,
)
from learning_pipeline.tools.elearning_bundle._authoring_workspace import (
    AuthoringFinding,
    FindingOwner,
    FindingRepairability,
    FindingSeverity,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    AuthoredScreenRequirement,
    ElearningAuthoringBrief,
    LearnerAction,
)


@dataclass(frozen=True)
class ApprovedAssessmentOption:
    option_id: str
    text: str
    correct: bool
    feedback: str


@dataclass(frozen=True)
class ApprovedAssessment:
    rlo_id: str
    assessment_id: str
    question_type: str
    stem: str
    options: tuple[ApprovedAssessmentOption, ...]


_ASSESSMENT_RE = re.compile(r"^Assessment \(([^)]+)\): (.*)$")
_OPTION_RE = re.compile(r"^  (\[CORRECT\] )?\(([^)]+)\) (.*)$")
_FEEDBACK_PREFIX = "    Feedback: "


def _parse_assessment(item: dict[str, Any]) -> ApprovedAssessment | None:
    content = item.get("content")
    if not isinstance(content, str):
        return None
    lines = content.splitlines()
    if not lines:
        return None
    heading = _ASSESSMENT_RE.match(lines[0])
    if heading is None:
        return None

    options: list[ApprovedAssessmentOption] = []
    index = 2 if len(lines) > 1 and lines[1] == "Options:" else 1
    while index < len(lines):
        option_match = _OPTION_RE.match(lines[index])
        if option_match is None:
            index += 1
            continue
        correct_marker, option_id, text = option_match.groups()
        index += 1
        feedback_parts: list[str] = []
        if index < len(lines) and lines[index].startswith(_FEEDBACK_PREFIX):
            feedback_parts.append(lines[index][len(_FEEDBACK_PREFIX):])
            index += 1
            while index < len(lines) and _OPTION_RE.match(lines[index]) is None:
                feedback_parts.append(lines[index].strip())
                index += 1
        options.append(
            ApprovedAssessmentOption(
                option_id=option_id,
                text=text,
                correct=correct_marker is not None,
                feedback="\n".join(feedback_parts),
            )
        )

    question_type = heading.group(1)
    correct_count = sum(option.correct for option in options)
    if question_type == "multiple_choice":
        question_type = (
            "multiple_choice_multi"
            if correct_count > 1
            else "multiple_choice_single"
        )
    if (
        question_type not in {"multiple_choice_single", "multiple_choice_multi"}
        or not 2 <= len(options) <= 5
        or (question_type == "multiple_choice_single" and correct_count != 1)
        or (question_type == "multiple_choice_multi" and correct_count < 1)
    ):
        return None

    assessment_id = item.get("content_id")
    rlo_id = item.get("rlo_id")
    if not isinstance(assessment_id, str) or not isinstance(rlo_id, str) or not options:
        return None
    return ApprovedAssessment(
        rlo_id=rlo_id,
        assessment_id=assessment_id,
        question_type=question_type,
        stem=heading.group(2),
        options=tuple(options),
    )


def extract_assessment_ledger(
    resolved_context: dict[str, Any],
) -> dict[str, tuple[ApprovedAssessment, ...]]:
    """Index approved assessments by authoritative modality scene ID."""
    ledger: dict[str, tuple[ApprovedAssessment, ...]] = {}
    scenes = resolved_context.get("scenes", ())
    if not isinstance(scenes, (list, tuple)):
        return ledger
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("scene_id"), str):
            continue
        assessments = tuple(
            parsed
            for item in scene.get("content_items", ())
            if isinstance(item, dict) and item.get("content_type") == "assessment_item"
            if (parsed := _parse_assessment(item)) is not None
        )
        if assessments:
            ledger[scene["scene_id"]] = assessments
    return ledger


def normalize_knowledge_check_requirements(
    brief: ElearningAuthoringBrief,
    resolved_context: dict[str, Any],
) -> ElearningAuthoringBrief:
    """Replace unsupported planned checks with grounded takeaway screens.

    An older or malformed workflow plan may request a knowledge check for
    scenes with no approved multiple-choice assessment. Inventing distractors
    violates RLO fidelity, while a free-text fallback does not match the
    Deloitte interaction pattern. Preserve the screen ID, ordering, and source
    lineage, but present the assigned material as key takeaways instead.
    """
    ledger = extract_assessment_ledger(resolved_context)
    requirements = []
    changed = False
    for requirement in brief.screen_requirements:
        if (
            isinstance(requirement, AuthoredScreenRequirement)
            and requirement.screen_type == "knowledge_check"
            and requirement.learner_action is None
            and not any(ledger.get(scene_id) for scene_id in requirement.source_scene_ids)
        ):
            requirement = requirement.model_copy(
                update={
                    "screen_type": "key_takeaways",
                    "learner_action": LearnerAction.CONSUME,
                    "content_direction": (
                        f"{requirement.content_direction} Present the approved points "
                        "as concise key takeaways rather than an assessment."
                    ),
                }
            )
            changed = True
        requirements.append(requirement)
    if not changed:
        return brief
    return brief.model_copy(update={"screen_requirements": tuple(requirements)})


def _question_matches(content: Any, approved: ApprovedAssessment) -> bool:
    if (
        content.question_id != approved.assessment_id
        or content.stem != approved.stem
        or content.question_type != approved.question_type
        or content.options is None
        or len(content.options) != len(approved.options)
    ):
        return False
    return all(
        generated.id == source.option_id
        and generated.text == source.text
        and generated.correct is source.correct
        and generated.feedback == source.feedback
        for generated, source in zip(content.options, approved.options, strict=True)
    )


def _draft_matches(
    screen: AuthoredScreenDraft, approved: ApprovedAssessment
) -> bool:
    return _question_matches(screen.content, approved)


def hydrate_approved_assessments(
    brief: ElearningAuthoringBrief,
    draft: ElearningCourseAuthorDraft,
    resolved_context: dict[str, Any],
) -> ElearningCourseAuthorDraft:
    """Replace model-transcribed assessment fields with authoritative source data.

    The model still selects and positions the knowledge-check screen. Exact
    assessment text, option order, correctness, and feedback are data-copying
    concerns and are therefore applied deterministically. If more than one
    approved item is assigned, retain the model's selected assessment ID when
    valid; otherwise select the first item in source order.
    """
    ledger = extract_assessment_ledger(resolved_context)
    requirements = {
        requirement.screen_id: requirement
        for requirement in brief.screen_requirements
        if isinstance(requirement, AuthoredScreenRequirement)
        and requirement.screen_type == "knowledge_check"
    }
    hydrated_screens: list[AuthoredScreenDraft] = []

    for screen in draft.authored_screens:
        requirement = requirements.get(screen.screen_id)
        if requirement is None or screen.screen_type != "knowledge_check":
            hydrated_screens.append(screen)
            continue
        candidates = tuple(
            assessment
            for scene_id in requirement.source_scene_ids
            for assessment in ledger.get(scene_id, ())
        )
        if not candidates:
            hydrated_screens.append(screen)
            continue
        selected = next(
            (
                assessment
                for assessment in candidates
                if assessment.assessment_id == screen.content.question_id
            ),
            candidates[0],
        )
        content = screen.content.model_copy(
            update={
                "question_id": selected.assessment_id,
                "stem": selected.stem,
                "question_type": selected.question_type,
                "options": [
                    KnowledgeCheckChoice(
                        id=option.option_id,
                        text=option.text,
                        correct=option.correct,
                        feedback=option.feedback,
                    )
                    for option in selected.options
                ],
                "questions": [
                    KnowledgeCheckQuestion(
                        question_id=assessment.assessment_id,
                        stem=assessment.stem,
                        question_type=assessment.question_type,
                        options=[
                            KnowledgeCheckChoice(
                                id=option.option_id,
                                text=option.text,
                                correct=option.correct,
                                feedback=option.feedback,
                            )
                            for option in assessment.options
                        ],
                    )
                    for assessment in candidates
                ],
            }
        )
        hydrated_screens.append(screen.model_copy(update={"content": content}))

    hydrated = tuple(hydrated_screens)
    if hydrated == draft.authored_screens:
        return draft
    return draft.model_copy(update={"authored_screens": hydrated})


def validate_assessment_fidelity(
    brief: ElearningAuthoringBrief,
    authored_screens: tuple[AuthoredScreenDraft, ...],
    resolved_context: dict[str, Any],
) -> tuple[AuthoringFinding, ...]:
    """Require exact approved assessment data for assigned knowledge checks."""
    ledger = extract_assessment_ledger(resolved_context)
    screens_by_id = {screen.screen_id: screen for screen in authored_screens}
    findings: list[AuthoringFinding] = []

    for requirement in brief.screen_requirements:
        if not isinstance(requirement, AuthoredScreenRequirement):
            continue
        if requirement.screen_type != "knowledge_check":
            continue
        assigned_items = tuple(
            item
            for scene in resolved_context.get("scenes", ())
            if isinstance(scene, dict)
            and scene.get("scene_id") in requirement.source_scene_ids
            for item in scene.get("content_items", ())
            if isinstance(item, dict) and item.get("content_type") == "assessment_item"
        )
        candidates = tuple(
            assessment
            for scene_id in requirement.source_scene_ids
            for assessment in ledger.get(scene_id, ())
        )
        if len(candidates) != len(assigned_items):
            findings.append(
                AuthoringFinding(
                    finding_id=f"assessment-source-invalid-{requirement.screen_id}",
                    code="ASSESSMENT_SOURCE_INVALID",
                    screen_id=requirement.screen_id,
                    category="assessment_source_invalid",
                    severity=FindingSeverity.BLOCKING,
                    owner=FindingOwner.SOURCE,
                    repairability=FindingRepairability.HUMAN_SOURCE,
                    message=(
                        "An assigned approved assessment could not be parsed into "
                        "an exact-copy ledger; fidelity cannot be verified."
                    ),
                    revision_instruction=(
                        "Do not publish this knowledge check until its resolved "
                        "assessment source is structurally readable."
                    ),
                )
            )
            continue
        # A workflow may request a generated formative check for a scene that has
        # no approved assessment item. Exact-copy enforcement applies only when
        # the assigned source scenes contain authoritative assessment content.
        if not candidates:
            continue
        screen = screens_by_id.get(requirement.screen_id)
        if screen is not None:
            grouped = screen.content.questions
            if grouped is not None and len(grouped) == len(candidates):
                if all(
                    _question_matches(question, approved)
                    for question, approved in zip(grouped, candidates, strict=True)
                ):
                    continue
            elif len(candidates) == 1 and _draft_matches(screen, candidates[0]):
                continue
        candidate_ids = tuple(
            f"{approved.rlo_id}:{approved.assessment_id}" for approved in candidates
        )
        digest = hashlib.sha256(
            f"{requirement.screen_id}:{candidate_ids}".encode("utf-8")
        ).hexdigest()[:12]
        findings.append(
            AuthoringFinding(
                finding_id=f"assessment-fidelity-{digest}",
                code="ASSESSMENT_FIDELITY_MISMATCH",
                screen_id=requirement.screen_id,
                category="assessment_fidelity",
                severity=FindingSeverity.BLOCKING,
                owner=FindingOwner.BUILDER,
                repairability=FindingRepairability.AUTOMATIC,
                message=(
                    "Knowledge-check wording, option IDs/order, correctness flags, "
                    "or diagnostic feedback differs from its approved assessment source."
                ),
                evidence=f"Approved assessment candidates: {candidate_ids}",
                revision_instruction=(
                    "Copy the assigned assessment stem, question type, option IDs, "
                    "option text, order, correctness flags, and feedback exactly."
                ),
            )
        )
    return tuple(findings)
