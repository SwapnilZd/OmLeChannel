"""Deterministic adapter from the seven-part authoring object to the catalog RLO."""

from __future__ import annotations

from rlo_schema import (
    AssessmentItem,
    AssessmentOption,
    Component,
    Concept,
    DesignBrief,
    EnablingObjective,
    GagneEventMapping,
    RLO,
)
from rlo_schema.v1 import (
    Accessibility,
    CDTType,
    Governance,
    Level,
    PerformanceLevel,
    RLOStatus,
    Rights,
    ScaffoldingLevel,
)

from .authoring_contracts import (
    AuthoringElement,
    AuthoringElementType,
    AuthoringRLORevision,
    ElementOrigin,
    PartStatus,
    RLOPartKind,
)


_PERFORMANCE_LEVEL = {
    "remember": PerformanceLevel.RECALL,
    "understand": PerformanceLevel.FIND,
    "apply": PerformanceLevel.DO,
    "analyze": PerformanceLevel.DECIDE,
    "evaluate": PerformanceLevel.DECIDE,
}


def _evidence_for_claims(authoring: AuthoringRLORevision, claim_refs: list[str]) -> list[str]:
    claims = {claim.claim_id: claim for claim in authoring.claims}
    return list(
        dict.fromkeys(
            evidence_ref
            for claim_ref in claim_refs
            for evidence_ref in claims[claim_ref].evidence_refs
        )
    )


def _component_type(element: AuthoringElement) -> CDTType:
    if element.element_type == AuthoringElementType.HOOK:
        return CDTType.HOOK
    if element.element_type == AuthoringElementType.WORKED_EXAMPLE:
        return CDTType.EXAMPLE
    if element.element_type in {
        AuthoringElementType.PRACTICE_ITEM,
        AuthoringElementType.PRIOR_KNOWLEDGE,
        AuthoringElementType.TRANSFER_PROMPT,
    }:
        return CDTType.RECALL_PROMPT
    return CDTType.RULE


def _concepts(authoring: AuthoringRLORevision) -> tuple[list[Concept], dict[str, str]]:
    evidence = {item.id: item for item in authoring.evidence}
    concepts = []
    concept_by_claim = {}
    for index, claim in enumerate(authoring.claims, start=1):
        concept_id = f"c-{index:03d}"
        concept_by_claim[claim.claim_id] = concept_id
        concepts.append(
            Concept(
                id=concept_id,
                name=f"Supported claim {index}",
                definition=claim.statement,
                elaboration=" ".join(claim.qualifications) or claim.statement,
                source_refs=list(
                    dict.fromkeys(evidence[ref].source_ref for ref in claim.evidence_refs)
                ),
                evidence_refs=claim.evidence_refs,
            )
        )
    return concepts, concept_by_claim


def _assessment(
    authoring: AuthoringRLORevision,
    element: AuthoringElement,
    concept_by_claim: dict[str, str],
    index: int,
) -> AssessmentItem:
    source = element.assessment
    if source is None:
        raise ValueError("assessment element has no assessment payload")
    claim_refs = list(dict.fromkeys([*element.claim_refs, *source.claim_refs]))
    concepts = list(dict.fromkeys(concept_by_claim[ref] for ref in claim_refs))
    evidence_refs = _evidence_for_claims(authoring, source.claim_refs)
    options = None
    if source.options is not None:
        options = [
            AssessmentOption(
                id=chr(65 + option_index),
                text=option.text,
                correct=option.correct,
                feedback=option.feedback,
                evidence_refs=_evidence_for_claims(authoring, option.claim_refs)
                if option.claim_refs
                else evidence_refs,
            )
            for option_index, option in enumerate(source.options)
        ]
    return AssessmentItem(
        id=f"q-{index:03d}",
        stem=source.stem,
        type=source.type,
        concepts_assessed=concepts,
        evidence_refs=evidence_refs,
        options=options,
        correct_response=source.correct_response,
        scoring_criteria=source.scoring_criteria,
        feedback_guidance=source.feedback_guidance,
        aligned_to_performance_level=_PERFORMANCE_LEVEL[
            authoring.classifications.target.bloom_level.value
        ],
    )


def adapt_authoring_rlo(authoring: AuthoringRLORevision) -> RLO:
    """Build one catalog RLO without asking a model to recreate the authoring work."""

    if any(part.status == PartStatus.SOURCE_INSUFFICIENT for part in authoring.parts):
        raise ValueError("source-insufficient authoring revisions cannot be adapted for publication")
    concepts, concept_by_claim = _concepts(authoring)
    objective_claims = [claim for claim in authoring.claims if claim.assessment_eligible]
    objective_concepts = [concept_by_claim[claim.claim_id] for claim in objective_claims]
    if not objective_concepts:
        raise ValueError("catalog RLO requires objective-defining claims")
    objective_evidence = _evidence_for_claims(
        authoring, [claim.claim_id for claim in objective_claims]
    )

    components = []
    assessment_items = []
    component_ids_by_part: dict[RLOPartKind, list[str]] = {
        part: [] for part in RLOPartKind
    }
    component_index = 0
    assessment_index = 0
    for part in authoring.parts:
        for element in part.elements:
            if element.element_type == AuthoringElementType.METADATA:
                continue
            if element.element_type == AuthoringElementType.ASSESSMENT_ITEM:
                assessment_index += 1
                assessment_items.append(
                    _assessment(authoring, element, concept_by_claim, assessment_index)
                )
                continue
            component_index += 1
            component_id = f"comp-{part.kind.value}-{component_index:03d}"
            claim_refs = element.claim_refs or [claim.claim_id for claim in objective_claims]
            components.append(
                Component(
                    id=component_id,
                    cdt_type=_component_type(element),
                    title=element.element_type.value.replace("_", " ").title(),
                    concepts_referenced=list(
                        dict.fromkeys(concept_by_claim[ref] for ref in claim_refs)
                    ),
                    evidence_refs=_evidence_for_claims(authoring, claim_refs),
                    canonical_content=(
                        element.assessment.model_dump(mode="json")
                        if element.assessment is not None
                        else {
                            "content": element.content,
                            "origin": element.origin.value,
                            "authoring_element_id": element.element_id,
                        }
                    ),
                )
            )
            component_ids_by_part[part.kind].append(component_id)

    if not components:
        raise ValueError("catalog RLO requires at least one instructional component")
    if not assessment_items:
        raise ValueError("catalog RLO requires at least one Check assessment")

    target = authoring.classifications.target
    observed = authoring.classifications.observed or target
    source_generated = sum(
        element.origin != ElementOrigin.SOURCE
        for part in authoring.parts
        for element in part.elements
    )
    return RLO(
        id=authoring.rlo_id,
        version=authoring.version,
        authoring_revision_id=authoring.authoring_revision_id,
        title=authoring.title,
        topic=authoring.topic,
        domain=authoring.domain,
        level=Level.INTRODUCTORY,
        audience=["Deloitte practitioners"],
        estimated_duration_minutes=authoring.estimated_duration_minutes,
        content_type=observed.content_type,
        performance_level=_PERFORMANCE_LEVEL[observed.bloom_level.value],
        prerequisites=authoring.relationships.prerequisites,
        corequisites=authoring.relationships.corequisites,
        follow_ons=authoring.relationships.follow_ons,
        related_rlos=authoring.relationships.related_rlos,
        sources=authoring.sources,
        evidence=authoring.evidence,
        terminal_objective=authoring.broader_outcome,
        performance_context=authoring.objective.performance_context,
        enabling_objective=EnablingObjective(
            id=authoring.objective.candidate_id,
            statement=authoring.objective.statement,
            bloom_level=observed.bloom_level,
            concepts_addressed=objective_concepts,
            evidence_refs=objective_evidence,
        ),
        concepts=concepts,
        components=components,
        assessment_items=assessment_items,
        design_brief=DesignBrief(
            tone="Clear, concise, and grounded in realistic Deloitte practitioner work.",
            scaffolding_level=ScaffoldingLevel.MEDIUM,
            scaffolding_notes="Use only the prior knowledge named in the approved authoring revision.",
            feedback_policy="Explain the supported decision basis without adding domain facts.",
            example_shape_hints=["Preserve visible expert reasoning from the Show part."],
            practice_shape_hints=[f"Exercise {target.content_type.value} × {target.bloom_level.value}."],
            salience_hook_description="Use the approved Set-up moment of need.",
        ),
        gagne_event_mapping=GagneEventMapping(
            event_1_gain_attention=component_ids_by_part[RLOPartKind.SETUP] or None,
            event_2_inform_objective="enabling_objective",
            event_3_stimulate_recall=component_ids_by_part[RLOPartKind.SETUP] or None,
            event_4_present_content=component_ids_by_part[RLOPartKind.TEACH] or None,
            event_5_provide_guidance=component_ids_by_part[RLOPartKind.SHOW] or None,
            event_6_elicit_performance=component_ids_by_part[RLOPartKind.PRACTICE] or None,
            event_7_provide_feedback=component_ids_by_part[RLOPartKind.PRACTICE] or None,
            event_8_assess_performance="assessment_items",
            event_9_enhance_retention=component_ids_by_part[RLOPartKind.SEND_OFF] or None,
        ),
        authoring_rationale=(
            f"Generated from seven-part authoring revision {authoring.authoring_revision_id}; "
            f"{source_generated} element(s) contain labeled generated scaffolding."
        ),
        governance=Governance(
            status=RLOStatus.DRAFT,
            authoring_sme="RLO generation pipeline",
            change_history=f"created from {authoring.authoring_revision_id}",
        ),
        accessibility=Accessibility(
            features=["plain_language", "screen_reader_optimised_structure"]
        ),
        rights=Rights(
            rights="internal_use_all_service_lines",
            sharing_constraints="internal only, not for external distribution",
        ),
    )
