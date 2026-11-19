"""Content-selection closure validation and deterministic expansion — Phase 12.

Behavior: automatically expand selection to include required concept dependencies
and record every addition in the report.  Never modifies canonical RLO objects.
Never invents content.
"""
from __future__ import annotations

from learning_pipeline.contracts.assembly import RLOContentSelection
from learning_pipeline.contracts.curriculum_assembly import (
    RLOAssemblyContext,
    TailoredRLODraft,
)


class ContentClosureError(ValueError):
    """Raised when a selected ID cannot be resolved against the canonical RLO."""

    def __init__(self, message: str, unknown_ids: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.unknown_ids = unknown_ids


def _all_concept_ids(ctx: RLOAssemblyContext) -> frozenset[str]:
    return frozenset(c.id for c in ctx.concepts)


def _all_component_ids(ctx: RLOAssemblyContext) -> frozenset[str]:
    return frozenset(c.id for c in ctx.components)


def _all_assessment_ids(ctx: RLOAssemblyContext) -> frozenset[str]:
    return frozenset(a.id for a in ctx.assessment_items)


def _all_objective_ids(ctx: RLOAssemblyContext) -> frozenset[str]:
    return frozenset({ctx.enabling_objective.id})


def validate_and_close_selection(
    draft: TailoredRLODraft,
    context: RLOAssemblyContext,
) -> tuple[RLOContentSelection, tuple[str, ...]]:
    """Validate selected IDs and deterministically expand required dependencies.

    Returns:
        (closed_selection, automatically_added_ids)
        automatically_added_ids lists every content ID added by closure.

    Raises:
        ContentClosureError — if selected IDs are unknown or empty selection.
    """
    all_concepts = _all_concept_ids(context)
    all_components = _all_component_ids(context)
    all_assessments = _all_assessment_ids(context)
    all_objectives = _all_objective_ids(context)

    sel = draft.selected_content

    # Validate all selected IDs exist in this RLO
    unknown: list[str] = []
    for oid in sel.objective_ids:
        if oid not in all_objectives:
            unknown.append(oid)
    for cid in sel.concept_ids:
        if cid not in all_concepts:
            unknown.append(cid)
    for cid in sel.component_ids:
        if cid not in all_components:
            unknown.append(cid)
    for aid in sel.assessment_item_ids:
        if aid not in all_assessments:
            unknown.append(aid)
    if unknown:
        raise ContentClosureError(
            f"RLO '{context.rlo_id}' v{context.rlo_version}: "
            f"selected content IDs not found: {unknown}",
            unknown_ids=tuple(unknown),
        )

    # Check non-empty: included RLO must select at least something
    total_selected = (
        len(sel.objective_ids)
        + len(sel.concept_ids)
        + len(sel.component_ids)
        + len(sel.assessment_item_ids)
    )
    # Empty RLOContentSelection means "select all" — treat that as valid
    # (the agent may leave all fields empty to indicate full selection)
    if total_selected == 0:
        # Return as-is (full selection)
        return sel, ()

    # Closure: collect required concept IDs from selected components/assessments
    selected_concepts = set(sel.concept_ids)
    added: list[str] = []

    # Build concept lookup
    component_map = {c.id: c for c in context.components}
    assessment_map = {a.id: a for a in context.assessment_items}

    for comp_id in sel.component_ids:
        comp = component_map[comp_id]
        for req_concept_id in comp.concepts_referenced:
            if req_concept_id not in selected_concepts and req_concept_id in all_concepts:
                selected_concepts.add(req_concept_id)
                added.append(req_concept_id)

    for ass_id in sel.assessment_item_ids:
        ass = assessment_map[ass_id]
        for req_concept_id in ass.concepts_assessed:
            if req_concept_id not in selected_concepts and req_concept_id in all_concepts:
                selected_concepts.add(req_concept_id)
                added.append(req_concept_id)

    if added:
        closed_sel = RLOContentSelection(
            objective_ids=sel.objective_ids,
            concept_ids=tuple(sorted(selected_concepts)),
            component_ids=sel.component_ids,
            assessment_item_ids=sel.assessment_item_ids,
        )
        return closed_sel, tuple(added)

    return sel, ()
