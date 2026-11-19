"""Compatibility adapter from stored shared-schema RLOs to assembly RLOs."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from learning_pipeline.contracts import RLODocument
from rlo_schema import RLO


class RLOCompatibilityError(ValueError):
    """A valid stored RLO cannot be represented by the downstream contract."""

    def __init__(self, rlo_id: str, reason: str) -> None:
        self.rlo_id = rlo_id
        self.reason = reason
        super().__init__(f"RLO {rlo_id!r} is incompatible with curriculum assembly: {reason}")


_DOWNSTREAM_GOVERNANCE_STATUS = {
    # Legacy shared-schema documents used "signed" for completed sign-off.
    # Normalize them while the object catalog is migrated to "approved".
    "signed": "approved",
}


def _many_event(value: str | list[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def adapt_stored_rlo(value: RLO | dict[str, Any]) -> RLODocument:
    """Validate and explicitly project one catalog RLO into `RLODocument`."""

    shared = value if isinstance(value, RLO) else RLO.model_validate(value)
    rlo_id = shared.id
    if shared.estimated_duration_minutes is None:
        raise RLOCompatibilityError(rlo_id, "estimated_duration_minutes is required")
    if shared.performance_level is None:
        raise RLOCompatibilityError(rlo_id, "performance_level is required")

    components: list[dict[str, Any]] = []
    for component in shared.components:
        if not isinstance(component.canonical_content, (str, dict)):
            raise RLOCompatibilityError(
                rlo_id,
                f"component {component.id!r} has unsupported list-shaped canonical_content",
            )
        components.append(
            {
                "id": component.id,
                "cdt_type": component.cdt_type.value,
                "title": component.title,
                "concepts_referenced": tuple(component.concepts_referenced),
                "misconceptions_addressed": tuple(component.misconceptions_addressed),
                "evidence_refs": tuple(component.evidence_refs),
                "canonical_content": component.canonical_content,
            }
        )

    assessment_items: list[dict[str, Any]] = []
    for item in shared.assessment_items:
        if item.options is None:
            raise RLOCompatibilityError(
                rlo_id,
                f"assessment item {item.id!r} has no options; open-response is not supported downstream",
            )
        assessment_items.append(
            {
                "id": item.id,
                "stem": item.stem,
                "type": item.type.value,
                "concepts_assessed": tuple(item.concepts_assessed),
                "evidence_refs": tuple(item.evidence_refs),
                "options": tuple(
                    {
                        "id": option.id,
                        "text": option.text,
                        "correct": option.correct,
                        "misconception_targeted": option.misconception_targeted,
                        "feedback": option.feedback,
                        "evidence_refs": tuple(option.evidence_refs),
                    }
                    for option in item.options
                ),
            }
        )

    gagne = shared.gagne_event_mapping
    payload = {
        "id": shared.id,
        "version": shared.version,
        "schema_version": shared.schema_version,
        "language": shared.language,
        "locale": shared.locale,
        "title": shared.title,
        "topic": shared.topic,
        "domain": shared.domain,
        "level": shared.level.value,
        "audience": tuple(shared.audience),
        "estimated_duration_minutes": shared.estimated_duration_minutes,
        "content_type": shared.content_type.value,
        "performance_level": shared.performance_level.value,
        "prerequisites": tuple(shared.prerequisites),
        "corequisites": tuple(shared.corequisites),
        "follow_ons": tuple(shared.follow_ons),
        "related_rlos": tuple(shared.related_rlos),
        "sources": tuple(source.model_dump(mode="json") for source in shared.sources),
        "evidence": tuple(item.model_dump(mode="json") for item in shared.evidence),
        "terminal_objective": shared.terminal_objective,
        "performance_context": shared.performance_context,
        "enabling_objective": shared.enabling_objective.model_dump(mode="json"),
        "concepts": tuple(concept.model_dump(mode="json") for concept in shared.concepts),
        "components": tuple(components),
        "assessment_items": tuple(assessment_items),
        "variant_examples": tuple(
            example.model_dump(mode="json") for example in shared.variant_examples
        ),
        "design_brief": shared.design_brief.model_dump(mode="json"),
        "gagne_event_mapping": {
            "event_1_gain_attention": _many_event(gagne.event_1_gain_attention),
            "event_2_inform_objective": _many_event(gagne.event_2_inform_objective),
            "event_3_stimulate_recall": _many_event(gagne.event_3_stimulate_recall),
            "event_4_present_content": _many_event(gagne.event_4_present_content),
            "event_5_provide_guidance": _many_event(gagne.event_5_provide_guidance),
            "event_6_elicit_performance": _many_event(gagne.event_6_elicit_performance),
            "event_7_provide_feedback": _many_event(gagne.event_7_provide_feedback),
            "event_8_assess_performance": _many_event(gagne.event_8_assess_performance),
            "event_9_enhance_retention": _many_event(gagne.event_9_enhance_retention),
        },
        "content_type_recommendations": tuple(
            recommendation.model_dump(mode="json")
            for recommendation in shared.content_type_recommendations
        ),
        "authoring_rationale": shared.authoring_rationale,
        "role_tags": tuple(shared.role_tags),
        "industry_tags": tuple(shared.industry_tags),
        "service_line_tags": tuple(shared.service_line_tags),
        "competency_map": tuple(shared.competency_map),
        "regulatory_tags": tuple(shared.regulatory_tags),
        "governance": {
            **shared.governance.model_dump(mode="json"),
            "status": _DOWNSTREAM_GOVERNANCE_STATUS.get(
                shared.governance.status.value,
                shared.governance.status.value,
            ),
        },
        "accessibility": shared.accessibility.model_dump(mode="json"),
    }
    try:
        return RLODocument.model_validate(payload)
    except ValidationError as exc:
        raise RLOCompatibilityError(rlo_id, str(exc)) from exc
