"""
Modality affordance catalog and production feasibility mapping — Phase 10.

Affordances describe *pedagogical presentation formats* for a modality.
They are planner-safe: no credentials, provider clients, or executor internals.

The feasibility layer maps affordances to required production capabilities,
allowing the planner to receive only currently producible affordances.
"""
from .catalog import ModalityAffordance, ModalityAffordanceCatalog, PlannerAffordanceView
from .feasibility import AffordanceSupportRule, compute_producible_affordances

__all__ = [
    "AffordanceSupportRule",
    "ModalityAffordance",
    "ModalityAffordanceCatalog",
    "PlannerAffordanceView",
    "compute_producible_affordances",
]
