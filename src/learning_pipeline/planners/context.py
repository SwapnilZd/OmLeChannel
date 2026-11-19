"""
PlanningContextResolver — Phase 9.

Resolves a CourseBlueprint + ModalityPlan into a ResolvedPlanningContext that
the Workflow Planner receives as its sole source of instructional content.

The resolver:
  1. Loads every RLO referenced by the blueprint.
  2. For each modality scene, extracts the exact content items referenced by that
     scene's RLOContentRef list.
  3. Converts typed RLO objects to plain-text ResolvedContentItems for the LLM.
  4. Preserves all source IDs so downstream tracing works correctly.

The resolver must NOT include content from RLOs that are not referenced by the
current modality plan's scenes.  Unrelated content is excluded from the LLM
context.
"""
from __future__ import annotations

import json
from typing import Any

from learning_pipeline.contracts import (
    CourseBlueprint,
    ModalityPlan,
    RLODocument,
)
from learning_pipeline.contracts.modality import RLOContentRef
from learning_pipeline.contracts.planning import (
    ResolvedContentItem,
    ResolvedPlanningContext,
    ResolvedSceneContext,
)
from learning_pipeline.repository import RLONotFoundError, RLORepository, RLOVersionNotFoundError


class PlanningContextError(RuntimeError):
    """Raised when context resolution cannot complete due to missing or invalid data."""


def _component_content_to_str(canonical_content: Any) -> str:
    """Convert canonical_content (str or dict) to a plain string."""
    if isinstance(canonical_content, str):
        return canonical_content
    return json.dumps(canonical_content, ensure_ascii=False)


def _extract_content_items(
    rlo: RLODocument,
    content_ref: RLOContentRef,
) -> list[ResolvedContentItem]:
    """Extract and convert the content items named in *content_ref* from *rlo*."""
    items: list[ResolvedContentItem] = []

    # Enabling objective (there is exactly one per RLO)
    for oid in content_ref.objective_ids:
        obj = rlo.enabling_objective
        if obj.id == oid:
            items.append(ResolvedContentItem(
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
            ))

    # Concepts
    concept_by_id = {c.id: c for c in rlo.concepts}
    for cid in content_ref.concept_ids:
        concept = concept_by_id.get(cid)
        if concept is None:
            continue
        # Include misconceptions inline for the LLM
        misc_text = ""
        if concept.misconceptions:
            misc_lines = [
                f"  - MISCONCEPTION: {m.statement} → CORRECTION: {m.correction}"
                for m in concept.misconceptions
            ]
            misc_text = "\nMisconceptions:\n" + "\n".join(misc_lines)
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

    # Instructional components
    component_by_id = {c.id: c for c in rlo.components}
    for cid in content_ref.component_ids:
        component = component_by_id.get(cid)
        if component is None:
            continue
        items.append(ResolvedContentItem(
            rlo_id=rlo.id,
            rlo_version=rlo.version,
            content_type="component",
            content_id=component.id,
            title=component.title,
            content=(
                f"CDT type: {component.cdt_type}\n"
                + (f"Title: {component.title}\n" if component.title else "")
                + f"Content: {_component_content_to_str(component.canonical_content)}"
            ),
            source_refs=(),
        ))

    # Assessment items
    item_by_id = {a.id: a for a in rlo.assessment_items}
    for aid in content_ref.assessment_item_ids:
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

    return items


class PlanningContextResolver:
    """Resolve RLO content into a self-contained ResolvedPlanningContext.

    Uses an RLORepository to load documents by ID and exact version.
    Only RLOs referenced by the blueprint AND appearing in at least one
    modality scene are included in the resolved context.
    """

    def __init__(self, rlo_repo: RLORepository) -> None:
        self._repo = rlo_repo

    async def resolve(
        self,
        blueprint: CourseBlueprint,
        modality_plan: ModalityPlan,
    ) -> ResolvedPlanningContext:
        """Resolve blueprint + modality plan into a ResolvedPlanningContext.

        Raises:
            PlanningContextError: If a referenced RLO cannot be loaded, or if
                an RLO version does not match the blueprint's declared version.
        """
        # 1. Load all RLOs declared by the blueprint
        rlo_by_id: dict[str, RLODocument] = {}
        for ref in blueprint.ordered_rlo_refs:
            try:
                rlo = await self._repo.get(ref.rlo_id, ref.rlo_version)
            except RLOVersionNotFoundError as exc:
                raise PlanningContextError(
                    f"RLO '{ref.rlo_id}' found but not at version '{ref.rlo_version}' "
                    f"(blueprint requires this exact version)"
                ) from exc
            except RLONotFoundError as exc:
                raise PlanningContextError(
                    f"RLO '{ref.rlo_id}' not found in repository"
                ) from exc
            if rlo.version != ref.rlo_version:
                raise PlanningContextError(
                    f"RLO '{ref.rlo_id}' version mismatch: "
                    f"expected '{ref.rlo_version}', got '{rlo.version}'"
                )
            rlo_by_id[rlo.id] = rlo

        # 2. Gather adaptation instructions from blueprint refs
        adaptation_instructions: list[str] = []
        design_tone = ""
        for ref in blueprint.ordered_rlo_refs:
            rlo = rlo_by_id.get(ref.rlo_id)
            if rlo is not None:
                design_tone = rlo.design_brief.tone
            adaptation_instructions.extend(ref.adaptation_instructions)

        # 3. Build per-scene resolved contexts
        resolved_scenes: list[ResolvedSceneContext] = []
        for scene in modality_plan.scenes:
            content_items: list[ResolvedContentItem] = []
            for content_ref in scene.source_content:
                rlo = rlo_by_id.get(content_ref.rlo_id)
                if rlo is None:
                    raise PlanningContextError(
                        f"Scene '{scene.id}' references RLO '{content_ref.rlo_id}' "
                        f"which is not declared in the blueprint"
                    )
                content_items.extend(_extract_content_items(rlo, content_ref))
            resolved_scenes.append(ResolvedSceneContext(
                scene_id=scene.id,
                learning_objective=scene.learning_objective,
                teaching_pattern=scene.teaching_pattern,
                target_duration_seconds=scene.target_duration_seconds,
                content_items=tuple(content_items),
            ))

        # 4. Collect accessibility requirements from RLOs
        accessibility_reqs: set[str] = set()
        for rlo in rlo_by_id.values():
            accessibility_reqs.update(rlo.accessibility.features)

        return ResolvedPlanningContext(
            blueprint_id=blueprint.blueprint_id,
            learner=blueprint.learner,
            scenes=tuple(resolved_scenes),
            brand_contract=dict(blueprint.brand_contract),
            accessibility_requirements=tuple(sorted(accessibility_reqs)),
            design_tone=design_tone,
            adaptation_instructions=tuple(adaptation_instructions),
        )
