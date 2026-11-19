"""Deterministic planning for bounded, reviewer-directed RLO revisions."""

from __future__ import annotations

import hashlib
import re

from .cell_scope import authoring_scope_error
from .draft_contracts import (
    DraftValidationFinding,
    RLODraftJob,
    RLORevisionAction,
    RLORevisionFindingOption,
    RLORevisionPlan,
    RLORevisionPlanRequest,
)


def finding_id(finding: DraftValidationFinding) -> str:
    normalized = " ".join(finding.message.casefold().split())
    value = "|".join((finding.category, finding.code, finding.path, normalized))
    return f"finding-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _targets(job: RLODraftJob, finding: DraftValidationFinding):
    authoring = job.authoring
    if authoring is None:
        return []
    path = finding.path
    matches = [
        (part, element)
        for part in authoring.parts
        for element in part.elements
        if element.element_id in path
    ]
    indexed = re.search(r"authoring\.parts\[(\d+)\]\.elements\[(\d+)\]", path)
    if not matches and indexed:
        part_index, element_index = map(int, indexed.groups())
        if part_index < len(authoring.parts):
            part = authoring.parts[part_index]
            if element_index < len(part.elements):
                matches.append((part, part.elements[element_index]))
    return matches


def revision_finding_options(job: RLODraftJob) -> list[RLORevisionFindingOption]:
    scope_error = authoring_scope_error(job.authoring)
    if scope_error:
        return [
            RLORevisionFindingOption(
                finding_id=finding_id(finding),
                code=finding.code,
                severity=finding.severity,
                message=finding.message,
                executable=False,
                stop_reason=f"RLO is outside POC2 authoring scope: {scope_error}",
            )
            for finding in job.findings
        ]
    options = []
    repeated = {
        finding_id
        for record in job.revision_history
        for finding_id in record.repeated_finding_ids
    }
    for finding in job.findings:
        stable_id = finding_id(finding)
        targets = _targets(job, finding)
        parts = list(dict.fromkeys(part.kind.value for part, _element in targets))
        element_ids = list(
            dict.fromkeys(element.element_id for _part, element in targets)
        )
        action = None
        stop_reason = None
        if not finding.repairable:
            stop_reason = "The validator did not mark this finding as repairable."
        elif not targets:
            stop_reason = "This finding does not identify an editable RLO element."
        elif finding.category == "classification":
            stop_reason = (
                "Changing the approved performance or interaction capability requires "
                "objective review, not another content repair."
            )
        elif finding.severity == "warning" and any(
            marker in finding.code.upper()
            for marker in ("PUNCTUATION", "EM_DASH", "READABILITY")
        ):
            stop_reason = (
                "This is an advisory writing note. Accept it or edit manually instead "
                "of spending model calls."
            )
        elif stable_id in repeated:
            stop_reason = (
                "This same finding survived its previous scoped repair. Choose a "
                "different action instead of spending another call."
            )
        elif finding.category == "grounding":
            action = RLORevisionAction.REPAIR_PROVENANCE
        elif set(parts) <= {"practice", "check"}:
            action = RLORevisionAction.REPAIR_ASSESSMENT
        else:
            action = RLORevisionAction.REPAIR_CONTENT
        options.append(
            RLORevisionFindingOption(
                finding_id=stable_id,
                code=finding.code,
                severity=finding.severity,
                message=finding.message,
                action=action,
                affected_parts=parts,
                affected_element_ids=element_ids,
                executable=action is not None,
                stop_reason=stop_reason,
            )
        )
    return options


def build_revision_plan(
    job: RLODraftJob, request: RLORevisionPlanRequest
) -> RLORevisionPlan:
    options = {item.finding_id: item for item in revision_finding_options(job)}
    missing = set(request.selected_finding_ids) - options.keys()
    if missing:
        raise ValueError("one or more selected findings are stale or unknown")
    selected = [options[item] for item in request.selected_finding_ids]
    stop_reason = next(
        (item.stop_reason for item in selected if not item.executable), None
    )
    if stop_reason is None and any(item.action != request.action for item in selected):
        stop_reason = "Selected findings require different revision actions."
    parts = list(
        dict.fromkeys(part for item in selected for part in item.affected_parts)
    )
    element_ids = list(
        dict.fromkeys(
            element_id for item in selected for element_id in item.affected_element_ids
        )
    )
    if not parts or not element_ids:
        stop_reason = stop_reason or "The selected findings have no editable scope."
    validator = (
        "provenance"
        if request.action == RLORevisionAction.REPAIR_PROVENANCE
        else "pedagogy"
    )
    reused = (
        job.authoring.provenance.operation_ids if job.authoring is not None else []
    )
    return RLORevisionPlan(
        action=request.action,
        selected_finding_ids=request.selected_finding_ids,
        affected_parts=parts,
        affected_element_ids=element_ids,
        required_validator=validator,
        reused_operations=reused,
        executable=stop_reason is None,
        stop_reason=stop_reason,
    )
