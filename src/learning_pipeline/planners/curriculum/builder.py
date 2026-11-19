"""Deterministic blueprint builder — Phase 12.

Converts a validated CourseAssemblyDraft into a CourseBlueprint.
Never calls an LLM. Given identical inputs and policy versions, produces
an identical blueprint.
"""
from __future__ import annotations

import uuid

from learning_pipeline.contracts.assembly import CourseBlueprint, TailoredRLORef
from learning_pipeline.contracts.common import PROFICIENCY_ORDER
from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyPlanningTrace,
    CourseAssemblyDraft,
    CourseAssemblyReport,
    CourseAssemblyRequest,
    CourseAssemblyResult,
    RLOAssemblyContext,
    RLOAssemblyDecision,
    TailoredRLODraft,
)
from learning_pipeline.contracts.planning import StructuredPlanningResponse

from .content_closure import validate_and_close_selection
from .duration import (
    DURATION_POLICY_VERSION,
    estimate_rlo_duration,
    estimate_total_duration,
)
from .governance import GOVERNANCE_POLICY_VERSION
from .prerequisites import validate_prerequisite_ordering
from .proficiency import PROFICIENCY_POLICY_VERSION, derive_starting_proficiency


class BlueprintBuildError(ValueError):
    """Raised when the deterministic builder cannot produce a valid blueprint."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def _bridge_strings(draft: CourseAssemblyDraft) -> tuple[str, ...]:
    return tuple(
        f"Bridge {b.bridge_id}: {b.before_rlo_id} — "
        f"topic '{b.prerequisite_topic}': {b.rationale}"
        for b in draft.prerequisite_bridges
    )


def _outcome_coverage(
    draft: CourseAssemblyDraft,
    contexts: dict[str, RLOAssemblyContext],
) -> dict[str, tuple[str, ...]]:
    """Build outcome→objective_ids coverage map."""
    all_objective_ids: list[str] = []
    for d in draft.ordered_rlo_drafts:
        ctx = contexts.get(d.rlo_id)
        if ctx is None:
            continue
        if d.selected_content.objective_ids:
            all_objective_ids.extend(d.selected_content.objective_ids)
        else:
            all_objective_ids.append(ctx.enabling_objective.id)
    return {
        outcome: tuple(all_objective_ids)
        for outcome in draft.learning_outcomes
    }


def build_blueprint(
    draft: CourseAssemblyDraft,
    request: CourseAssemblyRequest,
    eligible_contexts: tuple[RLOAssemblyContext, ...],
    governance_rejected: set[str],
    governance_warnings: list[str],
    planning_response: StructuredPlanningResponse,
    input_hash: str,
    blueprint_id: str | None = None,
) -> CourseAssemblyResult:
    """Convert a validated draft into a CourseBlueprint deterministically.

    Steps:
      1. Derive starting proficiency per RLO
      2. Validate content closure and expand if needed
      3. Validate proficiency regression
      4. Enforce contiguous ordering
      5. Validate prerequisites
      6. Estimate duration
      7. Validate duration limit
      8. Construct TailoredRLORef objects
      9. Construct CourseBlueprint
     10. Build CourseAssemblyReport
     11. Build AssemblyPlanningTrace
    """
    bid = blueprint_id or str(uuid.uuid4())
    context_map = {c.rlo_id: c for c in eligible_contexts}

    # Sort by draft order
    sorted_drafts = sorted(draft.ordered_rlo_drafts, key=lambda d: d.order)

    # Step 1: Derive starting proficiency for each RLO
    starting_proficiencies: dict[str, tuple] = {}
    for d in sorted_drafts:
        ctx = context_map.get(d.rlo_id)
        if ctx is None:
            raise BlueprintBuildError(
                f"Context not found for RLO '{d.rlo_id}' during blueprint build."
            )
        prof, source = derive_starting_proficiency(request.learner, ctx)
        starting_proficiencies[d.rlo_id] = (prof, source)

    # Step 2: Validate and close content selection
    closed_selections: dict[str, tuple] = {}
    for d in sorted_drafts:
        ctx = context_map[d.rlo_id]
        closed_sel, added = validate_and_close_selection(d, ctx)
        closed_selections[d.rlo_id] = (closed_sel, tuple(added))

    # Step 3: Validate proficiency regression
    for d in sorted_drafts:
        start_prof, _ = starting_proficiencies[d.rlo_id]
        if PROFICIENCY_ORDER[d.target_proficiency] < PROFICIENCY_ORDER[start_prof]:
            raise BlueprintBuildError(
                f"RLO '{d.rlo_id}': target_proficiency '{d.target_proficiency}' "
                f"is below starting_proficiency '{start_prof}'."
            )
        if request.constraints.minimum_target_proficiency:
            if (
                PROFICIENCY_ORDER[d.target_proficiency]
                < PROFICIENCY_ORDER[request.constraints.minimum_target_proficiency]
            ):
                raise BlueprintBuildError(
                    f"RLO '{d.rlo_id}': target_proficiency '{d.target_proficiency}' "
                    f"is below minimum required '{request.constraints.minimum_target_proficiency}'."
                )

    # Step 4: Validate contiguous ordering
    orders = [d.order for d in sorted_drafts]
    if orders != list(range(1, len(orders) + 1)):
        raise BlueprintBuildError(
            f"Draft orders must be contiguous starting at 1, got {orders}"
        )

    # Step 5: Validate prerequisites
    prereq_findings = validate_prerequisite_ordering(draft, context_map, request)

    # Step 6: Estimate duration
    starting_prof_map = {rid: v[0] for rid, v in starting_proficiencies.items()}
    estimated = estimate_total_duration(
        tuple(sorted_drafts),
        context_map,
        starting_prof_map,
        bridge_count=len(draft.prerequisite_bridges),
    )

    # Step 7: Validate duration limit
    limit = request.constraints.maximum_duration_minutes
    if limit is not None and estimated > limit:
        required_ids = set(request.constraints.required_rlo_ids)
        required_included = [
            d.rlo_id for d in sorted_drafts if d.rlo_id in required_ids
        ]
        duration_breakdown = {
            d.rlo_id: estimate_rlo_duration(
                d, context_map[d.rlo_id], starting_prof_map[d.rlo_id]
            )
            for d in sorted_drafts
        }
        required_description = (
            str(required_included) if required_included else "none explicitly required"
        )
        raise BlueprintBuildError(
            f"Estimated duration {estimated} min exceeds limit {limit} min. "
            f"Selected RLO duration breakdown: {duration_breakdown}. "
            f"Explicitly required RLOs: {required_description}. "
            "Reduce optional content or depth, or omit optional RLOs; "
            "do not silently omit required content."
        )

    if request.learner.duration_limit_minutes is not None:
        learner_limit = request.learner.duration_limit_minutes
        if estimated > learner_limit:
            raise BlueprintBuildError(
                f"Estimated duration {estimated} min exceeds learner limit {learner_limit} min."
            )

    # Step 8: Construct TailoredRLORef objects
    rlo_refs: list[TailoredRLORef] = []
    for d in sorted_drafts:
        start_prof, _ = starting_proficiencies[d.rlo_id]
        closed_sel, _ = closed_selections[d.rlo_id]
        rlo_refs.append(TailoredRLORef(
            rlo_id=d.rlo_id,
            rlo_version=d.rlo_version,
            order=d.order,
            selected_content=closed_sel,
            starting_proficiency=start_prof,
            target_proficiency=d.target_proficiency,
            content_depth=d.content_depth,
            role_relevance=d.role_relevance,
            example_context=d.example_context,
            personalization_rationale=d.personalization_rationale,
            sequencing_rationale=d.sequencing_rationale,
            adaptation_instructions=d.adaptation_instructions,
        ))

    # Step 9: Construct CourseBlueprint
    source_rlo_versions = {ref.rlo_id: ref.rlo_version for ref in rlo_refs}
    blueprint = CourseBlueprint(
        blueprint_id=bid,
        learner=request.learner,
        title=draft.title,
        learning_outcomes=draft.learning_outcomes,
        ordered_rlo_refs=tuple(rlo_refs),
        prerequisite_bridges=_bridge_strings(draft),
        brand_contract=dict(request.brand_contract),
        sequencing_rationale=draft.sequencing_rationale,
        assessment_strategy=draft.assessment_strategy,
        estimated_duration_minutes=estimated,
        source_rlo_versions=source_rlo_versions,
    )

    # Step 10: Build report
    candidate_decisions: list[RLOAssemblyDecision] = []

    for gid in sorted(governance_rejected):
        candidate_decisions.append(RLOAssemblyDecision(
            rlo_id=gid,
            rlo_version="",
            disposition="rejected_by_governance",
            rationale="Governance status not approved.",
        ))

    for d in sorted_drafts:
        start_prof, source = starting_proficiencies[d.rlo_id]
        _, auto_added = closed_selections[d.rlo_id]
        candidate_decisions.append(RLOAssemblyDecision(
            rlo_id=d.rlo_id,
            rlo_version=d.rlo_version,
            disposition="included",
            rationale=d.personalization_rationale,
            starting_proficiency_source=source,
            automatically_added_content_ids=auto_added,
        ))

    for o in draft.omitted_rlos:
        candidate_decisions.append(RLOAssemblyDecision(
            rlo_id=o.rlo_id,
            rlo_version=o.rlo_version,
            disposition="omitted",
            rationale=o.rationale,
        ))

    outcome_cov = _outcome_coverage(draft, context_map)
    warnings: list[str] = list(governance_warnings)

    report = CourseAssemblyReport(
        request_id=request.request_id,
        blueprint_id=bid,
        candidate_decisions=tuple(candidate_decisions),
        prerequisite_findings=tuple(prereq_findings),
        outcome_coverage=outcome_cov,
        duration_estimate_minutes=estimated,
        duration_policy_version=DURATION_POLICY_VERSION,
        warnings=tuple(warnings),
    )

    # Step 11: Build trace
    import hashlib, json as _json
    def _sha256(obj: object) -> str:
        return hashlib.sha256(
            _json.dumps(obj, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()

    draft_hash = _sha256(_json.loads(draft.model_dump_json()))
    blueprint_hash = _sha256(_json.loads(blueprint.model_dump_json()))

    trace = AssemblyPlanningTrace(
        assembly_request_id=request.request_id,
        blueprint_id=bid,
        candidate_snapshot_hash="",  # set by service
        learner_hash="",             # set by service
        constraints_hash="",         # set by service
        context_hash="",             # set by service
        prompt_version=planning_response.prompt_version,
        model=planning_response.model,
        draft_hash=draft_hash,
        blueprint_hash=blueprint_hash,
        assembly_policy_version=GOVERNANCE_POLICY_VERSION,
        duration_policy_version=DURATION_POLICY_VERSION,
        input_hash=input_hash,
        provider_request_id=planning_response.provider_request_id,
        input_tokens=planning_response.input_tokens,
        output_tokens=planning_response.output_tokens,
        estimated_cost_usd=planning_response.estimated_cost_usd,
    )

    return CourseAssemblyResult(
        blueprint=blueprint,
        report=report,
        trace=trace,
        from_cache=False,
    )
