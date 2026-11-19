"""Publication-boundary checks for learner-facing e-learning copy."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from learning_pipeline.tools.elearning_bundle._author_contracts import (
    _SCREEN_COPY_FIELDS,
    ElearningCourseAuthorDraft,
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
    resolved_learner_action,
)


# These are contextual signals, not a prohibited-word list. Deterministic matches
# are warnings; the semantic reviewer decides whether they are actually internal
# rationale or legitimate subject matter.
_RATIONALE_SIGNALS = (
    re.compile(
        r"\b(?:reduces?|lower(?:s|ing)?) (?:the )?"
        r"(?:recall|cognitive|memory) load\b",
        re.I,
    ),
    re.compile(
        r"\b(?:improves?|supports?|increases?) (?:learner )?"
        r"(?:retention|recall|engagement)\b",
        re.I,
    ),
    re.compile(r"\b(?:scaffold(?:s|ing)?|pedagogical rationale|instructional design)\b", re.I),
    re.compile(r"\bwithout changing the sequence\b", re.I),
)


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def build_learner_review_projection(
    course_dict: dict[str, Any],
    brief: ElearningAuthoringBrief,
    screen_ids: tuple[str, ...] | None = None,
    field_paths_by_screen: dict[str, tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Project validated course JSON to author-editable learner-visible fields."""
    allowed_ids = set(screen_ids or ())
    requirements = {
        requirement.screen_id: requirement
        for requirement in brief.screen_requirements
        if isinstance(requirement, AuthoredScreenRequirement)
    }
    projection: list[dict[str, Any]] = []
    for screen in course_dict.get("screens", ()):
        if not isinstance(screen, dict):
            continue
        screen_id = str(screen.get("screen_id", ""))
        requirement = requirements.get(screen_id)
        if requirement is None or (allowed_ids and screen_id not in allowed_ids):
            continue
        if requirement.screen_type == "knowledge_check":
            continue
        editable_fields = tuple(sorted(_SCREEN_COPY_FIELDS[requirement.screen_type]))
        if field_paths_by_screen is not None:
            requested_fields = {
                path.removeprefix("content.").split(".", 1)[0]
                for path in field_paths_by_screen.get(screen_id, ())
            }
            editable_fields = tuple(
                field for field in editable_fields if field in requested_fields
            )
        visible_content = {
            field: screen[field]
            for field in editable_fields
            if field in screen
        }
        projection.append(
            {
                "screen_id": screen_id,
                "screen_type": requirement.screen_type,
                "learner_purpose": requirement.content_direction,
                "learner_action": resolved_learner_action(requirement).value,
                "editable_fields": editable_fields,
                "learner_visible_content": visible_content,
            }
        )
    return tuple(projection)


def deterministic_review_projection(
    projection: tuple[dict[str, Any], ...],
) -> tuple[AuthoringFinding, ...]:
    findings: list[AuthoringFinding] = []
    for screen in projection:
        screen_id = str(screen["screen_id"])
        for text in _strings(screen.get("learner_visible_content", {})):
            if not any(pattern.search(text) for pattern in _RATIONALE_SIGNALS):
                continue
            digest = hashlib.sha256(
                f"{screen_id}:{text}".encode("utf-8")
            ).hexdigest()[:12]
            findings.append(
                AuthoringFinding(
                    finding_id=f"rationale-{digest}",
                    code="POSSIBLE_PEDAGOGICAL_RATIONALE_LEAKAGE",
                    screen_id=screen_id,
                    category="possible_internal_rationale",
                    severity=FindingSeverity.WARNING,
                    owner=FindingOwner.AUTHOR,
                    repairability=FindingRepairability.ADVISORY,
                    message=(
                        "Copy may explain why an instructional technique works instead "
                        "of teaching the approved subject matter."
                    ),
                    evidence=text[:500],
                    revision_instruction=(
                        "If this is production or pedagogical rationale rather than the "
                        "approved subject, remove it and state the learner task directly."
                    ),
                )
            )
    return tuple(findings)


def deterministic_review(
    draft: ElearningCourseAuthorDraft,
) -> tuple[AuthoringFinding, ...]:
    """Flag likely boundary leakage without pretending lexical matches are proof."""
    findings: list[AuthoringFinding] = []
    for screen in draft.authored_screens:
        for text in _strings(screen.content.model_dump(exclude_none=True)):
            if not any(pattern.search(text) for pattern in _RATIONALE_SIGNALS):
                continue
            digest = hashlib.sha256(
                f"{screen.screen_id}:{text}".encode("utf-8")
            ).hexdigest()[:12]
            findings.append(
                AuthoringFinding(
                    finding_id=f"rationale-{digest}",
                    code="POSSIBLE_PEDAGOGICAL_RATIONALE_LEAKAGE",
                    screen_id=screen.screen_id,
                    category="possible_internal_rationale",
                    severity=FindingSeverity.WARNING,
                    owner=FindingOwner.AUTHOR,
                    repairability=FindingRepairability.ADVISORY,
                    message=(
                        "Copy may explain why an instructional technique works instead "
                        "of teaching the approved subject matter."
                    ),
                    evidence=text[:500],
                    revision_instruction=(
                        "If this is production or pedagogical rationale rather than the "
                        "approved subject, remove it and state the learner task directly."
                    ),
                )
            )
    return tuple(findings)
