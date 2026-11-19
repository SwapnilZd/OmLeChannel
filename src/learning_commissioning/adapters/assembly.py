"""Build the existing assembly contract from a confirmed learning request."""

from __future__ import annotations

import hashlib
import json

from pydantic import Field

from learning_pipeline.contracts import (
    AssemblyRLOCandidate,
    CourseAssemblyConstraints,
    CourseAssemblyRequest,
    LearnerContext,
)
from learning_pipeline.contracts.common import PROFICIENCY_ORDER, FrozenModel

from learning_commissioning.contracts import (
    AudienceProfile,
    ConfirmedLearningRequest,
    LearningCommissionRequest,
    RLOCandidateDisposition,
)

ASSEMBLY_ADAPTER_POLICY_VERSION = "commissioning-assembly-adapter-v1"


class AssemblyAdapterError(ValueError):
    """A confirmed commissioning snapshot cannot form a valid assembly request."""


class AssemblyAdapterTrace(FrozenModel):
    policy_version: str = ASSEMBLY_ADAPTER_POLICY_VERSION
    commission_request_id: str
    preview_id: str
    adapter_decisions: tuple[str, ...]
    retrieval_excluded_rlo_ids: tuple[str, ...]
    assembly_excluded_rlo_ids: tuple[str, ...]
    request_hash: str = Field(min_length=1)


class AssemblyAdapterResult(FrozenModel):
    request: CourseAssemblyRequest
    trace: AssemblyAdapterTrace


def _hash_model(model: FrozenModel) -> str:
    payload = json.loads(model.model_dump_json())
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def project_audience_to_learner(
    audience: AudienceProfile,
    *,
    goals: tuple[str, ...],
    duration_limit_minutes: int | None,
) -> tuple[LearnerContext, tuple[str, ...]]:
    """Project available request attributes into the singular learner contract."""

    notes = [
        "LearnerContext represents the individual using the self-service request.",
        "Available learner attributes are preserved in business_context.",
    ]
    if len(audience.deloitte_levels) == 1:
        deloitte_level = audience.deloitte_levels[0]
    else:
        deloitte_level = None
        if audience.deloitte_levels:
            notes.append(
                "deloitte_level was left unset because multiple possible levels were supplied."
            )

    context = dict(audience.business_context)
    context.update(
        {
            "audience_kind": "individual",
            "target_roles": " | ".join(audience.roles),
            "target_deloitte_levels": " | ".join(str(level) for level in audience.deloitte_levels),
            "industries": " | ".join(audience.industries),
            "service_lines": " | ".join(audience.service_lines),
            "language": audience.language,
            "locale": audience.locale,
            "target_proficiency": audience.target_proficiency.value,
        }
    )
    learner = LearnerContext(
        role=" / ".join(audience.roles) or "Individual learner",
        deloitte_level=deloitte_level,
        default_proficiency=audience.current_proficiency,
        topic_proficiencies={},
        goals=goals,
        duration_limit_minutes=duration_limit_minutes,
        business_context=context,
    )
    return learner, tuple(notes)


def build_course_assembly_request(
    commission: LearningCommissionRequest,
    confirmed: ConfirmedLearningRequest,
) -> AssemblyAdapterResult:
    """Create a validated downstream assembly request without semantic inference."""

    if commission.request_id != confirmed.request_id:
        raise AssemblyAdapterError("commission and confirmation request IDs do not match")

    by_id = {candidate.rlo_id: candidate for candidate in confirmed.candidates}
    missing_required = set(commission.required_rlo_ids) - set(by_id)
    if missing_required:
        raise AssemblyAdapterError(
            f"required RLOs are missing from the confirmed snapshot: {sorted(missing_required)}"
        )
    wrongly_required = [
        rlo_id
        for rlo_id in commission.required_rlo_ids
        if by_id[rlo_id].disposition != RLOCandidateDisposition.REQUIRED
    ]
    if wrongly_required:
        raise AssemblyAdapterError(
            f"user-required RLOs must remain required at confirmation: {sorted(wrongly_required)}"
        )

    forbidden_inclusions = [
        candidate.rlo_id
        for candidate in confirmed.candidates
        if candidate.rlo_id in commission.excluded_rlo_ids
        and candidate.disposition != RLOCandidateDisposition.EXCLUDE
    ]
    if forbidden_inclusions:
        raise AssemblyAdapterError(
            f"explicitly excluded RLOs cannot be included: {sorted(forbidden_inclusions)}"
        )

    assembly_candidates = tuple(
        AssemblyRLOCandidate(
            rlo_id=candidate.rlo_id,
            rlo_version=candidate.rlo_version,
            required=candidate.disposition == RLOCandidateDisposition.REQUIRED,
        )
        for candidate in confirmed.candidates
    )
    required_ids = tuple(
        candidate.rlo_id
        for candidate in confirmed.candidates
        if candidate.disposition == RLOCandidateDisposition.REQUIRED
    )
    excluded_ids = tuple(
        candidate.rlo_id
        for candidate in confirmed.candidates
        if candidate.disposition == RLOCandidateDisposition.EXCLUDE
    )

    adapter_decisions: list[str] = []
    goals = commission.stated_goals or (confirmed.confirmed_course_goal,)
    if not commission.stated_goals:
        adapter_decisions.append(
            "LearnerContext.goals defaulted to the requester-confirmed course goal."
        )
    learner, projection_notes = project_audience_to_learner(
        commission.audience,
        goals=goals,
        duration_limit_minutes=commission.duration_limit_minutes,
    )

    target = commission.audience.target_proficiency
    minimum = commission.minimum_target_proficiency
    if minimum is None or PROFICIENCY_ORDER[target] >= PROFICIENCY_ORDER[minimum]:
        minimum = target
        adapter_decisions.append(
            "minimum_target_proficiency set from the learner target proficiency."
        )
    if commission.excluded_rlo_ids:
        adapter_decisions.append(
            "Request-level excluded RLO IDs were enforced during retrieval; only excluded "
            "candidates present in the confirmed snapshot are repeated in assembly constraints."
        )

    request = CourseAssemblyRequest(
        request_id=commission.request_id,
        learner=learner,
        candidates=assembly_candidates,
        course_goal=confirmed.confirmed_course_goal,
        constraints=CourseAssemblyConstraints(
            required_rlo_ids=required_ids,
            excluded_rlo_ids=excluded_ids,
            required_content_ids=(),
            maximum_duration_minutes=commission.duration_limit_minutes,
            minimum_target_proficiency=minimum,
        ),
        brand_contract=commission.brand_contract,
    )
    trace = AssemblyAdapterTrace(
        commission_request_id=commission.request_id,
        preview_id=confirmed.preview_id,
        adapter_decisions=projection_notes + tuple(adapter_decisions),
        retrieval_excluded_rlo_ids=commission.excluded_rlo_ids,
        assembly_excluded_rlo_ids=excluded_ids,
        request_hash=_hash_model(request),
    )
    return AssemblyAdapterResult(request=request, trace=trace)
