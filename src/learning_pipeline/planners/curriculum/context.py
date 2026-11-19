"""Deterministic assembly-context projection builder — Phase 12."""
from __future__ import annotations

import json

from learning_pipeline.contracts.curriculum_assembly import RLOAssemblyContext
from learning_pipeline.contracts.rlo import RLODocument


def build_assembly_context(rlo: RLODocument) -> RLOAssemblyContext:
    """Build a deterministic read-only context projection from a canonical RLO.

    Does not invoke an LLM.  Copies only typed fields — never modifies the RLO.
    """
    source_ids = tuple(s.id for s in rlo.sources)
    return RLOAssemblyContext(
        rlo_id=rlo.id,
        rlo_version=rlo.version,
        title=rlo.title,
        topic=rlo.topic,
        domain=rlo.domain,
        level=rlo.level,
        audience=rlo.audience,
        estimated_duration_minutes=rlo.estimated_duration_minutes,
        prerequisites=rlo.prerequisites,
        corequisites=rlo.corequisites,
        follow_ons=rlo.follow_ons,
        terminal_objective=rlo.terminal_objective,
        enabling_objective=rlo.enabling_objective,
        concepts=rlo.concepts,
        components=rlo.components,
        assessment_items=rlo.assessment_items,
        design_brief=rlo.design_brief,
        content_type_recommendations=rlo.content_type_recommendations,
        role_tags=rlo.role_tags,
        industry_tags=rlo.industry_tags,
        service_line_tags=rlo.service_line_tags,
        competency_map=rlo.competency_map,
        regulatory_tags=rlo.regulatory_tags,
        governance_status=rlo.governance.status,
        source_ids=source_ids,
    )


def serialized_context_size(contexts: tuple[RLOAssemblyContext, ...]) -> int:
    """Return the serialized byte size of the context payload."""
    payload = [json.loads(c.model_dump_json()) for c in contexts]
    return len(json.dumps(payload, ensure_ascii=False))


class ContextBudgetExceededError(RuntimeError):
    """Raised when the assembled context exceeds the configured token/size budget."""

    def __init__(self, calculated_size: int, budget: int) -> None:
        super().__init__(
            f"Assembly context size {calculated_size:,} chars exceeds budget {budget:,} chars. "
            "Reduce candidate set or use hierarchical assembly."
        )
        self.calculated_size = calculated_size
        self.budget = budget


def check_context_budget(
    contexts: tuple[RLOAssemblyContext, ...],
    budget_chars: int,
) -> None:
    """Raise ContextBudgetExceededError if the serialized context is too large.

    Never silently truncates candidates or content.
    """
    size = serialized_context_size(contexts)
    if size > budget_chars:
        raise ContextBudgetExceededError(size, budget_chars)
