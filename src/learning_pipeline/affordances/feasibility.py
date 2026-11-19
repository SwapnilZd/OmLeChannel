"""
Production feasibility mapping for modality affordances — Phase 10.

Maps pedagogical affordances to the production capabilities they require.
Before giving the Modality Planner its affordance view, the available
production capability set is checked and only producible affordances are
included.

The Modality Planner never sees raw task types, provider details, or
executor implementation details — only the filtered PlannerAffordanceView.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import FrozenModel, Modality

from .catalog import ModalityAffordanceCatalog, PlannerAffordanceView


class AffordanceSupportRule(FrozenModel):
    """
    Declares which production capabilities an affordance requires.

    If all ``required_capabilities`` are present in the available capability
    set, the affordance is producible and may be included in the planner view.
    """

    modality: Modality
    affordance_id: str
    required_capabilities: tuple[str, ...]


def compute_producible_affordances(
    catalog: ModalityAffordanceCatalog,
    support_rules: tuple[AffordanceSupportRule, ...],
    available_capabilities: frozenset[str],
    modality: Modality,
) -> PlannerAffordanceView:
    """Return a PlannerAffordanceView containing only currently producible affordances.

    An affordance is producible if every capability listed in its support rule
    is present in ``available_capabilities``.  Affordances with no matching
    rule are excluded (they are considered unsupported).

    Affordances are returned in deterministic (lexicographic) order by ID.
    Raw task types are never exposed in the returned view.
    """
    rule_by_id: dict[str, AffordanceSupportRule] = {
        rule.affordance_id: rule
        for rule in support_rules
        if rule.modality == modality
    }

    producible = []
    for affordance in catalog.affordances_for(modality):
        rule = rule_by_id.get(affordance.id)
        if rule is None:
            continue
        if all(cap in available_capabilities for cap in rule.required_capabilities):
            producible.append(affordance)

    return PlannerAffordanceView(
        modality=modality,
        affordances=tuple(producible),
    )
