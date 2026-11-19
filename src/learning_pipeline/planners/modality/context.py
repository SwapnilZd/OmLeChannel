"""
ModalityContextResolver — Phase 10.

Resolves a CourseBlueprint into a ModalityPlanningContext that the Modality
Planner receives as its sole source of instructional content.

The resolver:
  1. Loads every RLO referenced by blueprint.ordered_rlo_refs.
  2. Filters each RLO's content to what the TailoredRLORef selected.
  3. Converts typed RLO objects to plain-text ResolvedContentItems.
  4. Preserves blueprint ordering, source IDs, and personalization directives.

The resolver must NOT load unrelated RLO content.  Only content explicitly
selected in TailoredRLORef.selected_content is included.
"""
from __future__ import annotations

import json
from typing import Any

from learning_pipeline.contracts.assembly import RLOContentSelection, TailoredRLORef
from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.contracts import CourseBlueprint, RLODocument
from learning_pipeline.contracts.planning import (
    ModalityPlanningContext,
    ResolvedContentItem,
    ResolvedRLOContext,
)
from learning_pipeline.repository import (
    RLONotFoundError,
    RLORepository,
    RLOVersionNotFoundError,
)


class ModalityContextError(RuntimeError):
    """Raised when context resolution fails due to missing or invalid data."""


def _component_content_to_str(canonical_content: Any) -> str:
    if isinstance(canonical_content, str):
        return canonical_content
    return json.dumps(canonical_content, ensure_ascii=False)


def _selects_full_rlo(selected: RLOContentSelection) -> bool:
    """All-empty is the sole shorthand for selecting the complete RLO."""
    return not any(
        (
            selected.objective_ids,
            selected.concept_ids,
            selected.component_ids,
            selected.assessment_item_ids,
        )
    )


def _resolve_objectives(
    rlo: RLODocument,
    selected: RLOContentSelection,
) -> tuple[ResolvedContentItem, ...]:
    """Return the enabling objective if it is selected."""
    obj = rlo.enabling_objective
    selected_ids = selected.objective_ids
    if not _selects_full_rlo(selected) and obj.id not in selected_ids:
        return ()
    return (
        ResolvedContentItem(
            rlo_id=rlo.id,
            rlo_version=rlo.version,
            content_type="objective",
            content_id=obj.id,
            title=None,
            content=(
                f"Learning objective: {obj.statement}\n"
                f"Bloom level: {obj.bloom_level}"
            ),
            source_refs=(),
        ),
    )


def _resolve_concepts(
    rlo: RLODocument,
    selected: RLOContentSelection,
) -> tuple[ResolvedContentItem, ...]:
    concept_by_id = {c.id: c for c in rlo.concepts}
    ids_to_include = (
        tuple(concept_by_id.keys())
        if _selects_full_rlo(selected)
        else selected.concept_ids
    )
    items: list[ResolvedContentItem] = []
    for cid in ids_to_include:
        concept = concept_by_id.get(cid)
        if concept is None:
            continue
        misc_text = ""
        if concept.misconceptions:
            lines = [
                f"  - MISCONCEPTION: {m.statement} → CORRECTION: {m.correction}"
                for m in concept.misconceptions
            ]
            misc_text = "\nMisconceptions:\n" + "\n".join(lines)
        items.append(ResolvedContentItem(
            rlo_id=rlo.id,
            rlo_version=rlo.version,
            content_type="concept",
            content_id=concept.id,
            title=concept.name,
            content=(
                f"Concept: {concept.name}\n"
                f"Definition: {concept.definition}\n"
                f"Elaboration: {concept.elaboration}"
                + misc_text
            ),
            source_refs=tuple(concept.source_refs),
        ))
    return tuple(items)


def _resolve_components(
    rlo: RLODocument,
    selected: RLOContentSelection,
) -> tuple[ResolvedContentItem, ...]:
    comp_by_id = {c.id: c for c in rlo.components}
    ids_to_include = (
        tuple(comp_by_id.keys())
        if _selects_full_rlo(selected)
        else selected.component_ids
    )
    items: list[ResolvedContentItem] = []
    for cid in ids_to_include:
        comp = comp_by_id.get(cid)
        if comp is None:
            continue
        items.append(ResolvedContentItem(
            rlo_id=rlo.id,
            rlo_version=rlo.version,
            content_type="component",
            content_id=comp.id,
            title=comp.title,
            content=(
                f"CDT type: {comp.cdt_type}\n"
                + (f"Title: {comp.title}\n" if comp.title else "")
                + f"Content: {_component_content_to_str(comp.canonical_content)}"
            ),
            source_refs=(),
        ))
    return tuple(items)


def _resolve_assessments(
    rlo: RLODocument,
    selected: RLOContentSelection,
) -> tuple[ResolvedContentItem, ...]:
    item_by_id = {a.id: a for a in rlo.assessment_items}
    ids_to_include = (
        tuple(item_by_id.keys())
        if _selects_full_rlo(selected)
        else selected.assessment_item_ids
    )
    items: list[ResolvedContentItem] = []
    for aid in ids_to_include:
        item = item_by_id.get(aid)
        if item is None:
            continue
        options_text = "\n".join(
            f"  {'[CORRECT] ' if opt.correct else ''}({opt.id}) {opt.text}\n"
            f"    Feedback: {opt.feedback}"
            for opt in item.options
        )
        items.append(ResolvedContentItem(
            rlo_id=rlo.id,
            rlo_version=rlo.version,
            content_type="assessment_item",
            content_id=item.id,
            title=item.stem[:60] if len(item.stem) > 60 else item.stem,
            content=(
                f"Assessment ({item.type}): {item.stem}\n"
                f"Options:\n{options_text}"
            ),
            source_refs=(),
        ))
    return tuple(items)


def _selected_ids_for(rlo: RLODocument, selected: RLOContentSelection, content_type: str) -> tuple[str, ...]:
    """Expand an all-empty full-RLO selection to explicit ID tuples."""
    full_rlo = _selects_full_rlo(selected)
    if content_type == "objective":
        ids = selected.objective_ids
        return (rlo.enabling_objective.id,) if full_rlo else ids
    if content_type == "concept":
        ids = selected.concept_ids
        return tuple(c.id for c in rlo.concepts) if full_rlo else ids
    if content_type == "component":
        ids = selected.component_ids
        return tuple(c.id for c in rlo.components) if full_rlo else ids
    if content_type == "assessment":
        ids = selected.assessment_item_ids
        return tuple(a.id for a in rlo.assessment_items) if full_rlo else ids
    raise ValueError(f"Unknown content_type: {content_type!r}")


class ModalityContextResolver:
    """Resolve a CourseBlueprint into a self-contained ModalityPlanningContext.

    Uses an RLORepository to load documents by ID and exact version.
    Only selected content from each TailoredRLORef is included.
    """

    def __init__(self, rlo_repo: RLORepository) -> None:
        self._repo = rlo_repo

    async def resolve(self, blueprint: CourseBlueprint) -> ModalityPlanningContext:
        """Resolve blueprint into a ModalityPlanningContext.

        Raises:
            ModalityContextError: If a referenced RLO cannot be loaded, or
                if an RLO version does not match the blueprint declaration.
        """
        rlo_by_id: dict[str, RLODocument] = {}
        for ref in blueprint.ordered_rlo_refs:
            try:
                rlo = await self._repo.get(ref.rlo_id, ref.rlo_version)
            except RLOVersionNotFoundError as exc:
                raise ModalityContextError(
                    f"RLO '{ref.rlo_id}' found but not at version '{ref.rlo_version}'"
                ) from exc
            except RLONotFoundError as exc:
                raise ModalityContextError(
                    f"RLO '{ref.rlo_id}' not found in repository"
                ) from exc
            if rlo.version != ref.rlo_version:
                raise ModalityContextError(
                    f"RLO '{ref.rlo_id}' version mismatch: "
                    f"expected '{ref.rlo_version}', got '{rlo.version}'"
                )
            rlo_by_id[rlo.id] = rlo

        # Build per-RLO resolved contexts, preserving blueprint order
        sorted_refs = sorted(blueprint.ordered_rlo_refs, key=lambda r: r.order)
        rlo_contexts: list[ResolvedRLOContext] = []
        design_tone = ""
        for ref in sorted_refs:
            rlo = rlo_by_id[ref.rlo_id]
            design_tone = rlo.design_brief.tone
            sel = ref.selected_content
            rlo_contexts.append(ResolvedRLOContext(
                rlo_id=rlo.id,
                rlo_version=rlo.version,
                order=ref.order,
                title=rlo.title,
                topic=rlo.topic,
                terminal_objective_text=rlo.terminal_objective,
                enabling_objectives=_resolve_objectives(rlo, sel),
                concepts=_resolve_concepts(rlo, sel),
                components=_resolve_components(rlo, sel),
                assessment_items=_resolve_assessments(rlo, sel),
                selected_objective_ids=_selected_ids_for(rlo, sel, "objective"),
                selected_concept_ids=_selected_ids_for(rlo, sel, "concept"),
                selected_component_ids=_selected_ids_for(rlo, sel, "component"),
                selected_assessment_ids=_selected_ids_for(rlo, sel, "assessment"),
                role_relevance=ref.role_relevance,
                example_context=ref.example_context,
                adaptation_instructions=ref.adaptation_instructions,
            ))

        # Collect accessibility requirements
        accessibility_reqs: set[str] = set()
        for rlo in rlo_by_id.values():
            accessibility_reqs.update(rlo.accessibility.features)

        return ModalityPlanningContext(
            blueprint_id=blueprint.blueprint_id,
            learner=blueprint.learner,
            rlo_contexts=tuple(rlo_contexts),
            prerequisite_bridges=blueprint.prerequisite_bridges,
            assessment_strategy=blueprint.assessment_strategy,
            brand_contract=dict(blueprint.brand_contract),
            accessibility_requirements=tuple(sorted(accessibility_reqs)),
            design_tone=design_tone,
            estimated_duration_minutes=blueprint.estimated_duration_minutes,
        )
