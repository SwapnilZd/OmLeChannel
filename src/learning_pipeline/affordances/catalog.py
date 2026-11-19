"""
ModalityAffordanceCatalog — planner-safe affordance registry.

An affordance describes a supported way to teach content in a given modality.
This module contains NO production tool internals, provider credentials,
executor factories, or code-generation prompts.
"""
from __future__ import annotations

from typing import Iterable

from pydantic import Field

from learning_pipeline.contracts.common import FrozenModel, Modality


class ModalityAffordance(FrozenModel):
    """
    One pedagogical presentation format for a modality.

    Answers: *how is a scene presented in the chosen modality?*
    Contains no production tool details, executor logic, or provider info.
    """

    id: str
    modality: Modality
    description: str
    pedagogical_uses: tuple[str, ...]
    constraints: dict[str, str] = Field(default_factory=dict)
    suitable_narrative_roles: tuple[str, ...] = ()
    accessibility_notes: tuple[str, ...] = ()


class PlannerAffordanceView(FrozenModel):
    """
    Serializable view of affordances the Modality Planner may use.

    Contains only currently producible affordances for the requested modality.
    Computed by ``compute_producible_affordances`` at planning time.
    """

    modality: Modality
    affordances: tuple[ModalityAffordance, ...]

    def affordance_ids(self) -> frozenset[str]:
        return frozenset(a.id for a in self.affordances)

    def resolve(self, affordance_id: str) -> ModalityAffordance:
        for a in self.affordances:
            if a.id == affordance_id:
                return a
        raise KeyError(f"Affordance {affordance_id!r} not in view for {self.modality}")


class _DuplicateAffordanceError(ValueError):
    pass


class _UnknownAffordanceError(KeyError):
    pass


class ModalityAffordanceCatalog:
    """Registry of pedagogical affordances, keyed by modality and ID.

    Duplicate affordance IDs within a modality are rejected at registration.
    Affordances are returned in deterministic (lexicographic) order by ID.
    Contains no production tool internals or executor factories.
    """

    def __init__(self, affordances: Iterable[ModalityAffordance]) -> None:
        self._by_modality: dict[Modality, dict[str, ModalityAffordance]] = {}
        for affordance in affordances:
            mod = affordance.modality
            if mod not in self._by_modality:
                self._by_modality[mod] = {}
            if affordance.id in self._by_modality[mod]:
                raise _DuplicateAffordanceError(
                    f"Duplicate affordance ID {affordance.id!r} for modality {mod!r}"
                )
            self._by_modality[mod][affordance.id] = affordance

    def affordances_for(self, modality: Modality) -> tuple[ModalityAffordance, ...]:
        """Return all affordances for a modality, ordered by ID."""
        by_id = self._by_modality.get(modality, {})
        return tuple(sorted(by_id.values(), key=lambda a: a.id))

    def resolve(self, modality: Modality, affordance_id: str) -> ModalityAffordance:
        """Return one affordance by modality + ID.

        Raises ``KeyError`` if the affordance is not registered.
        """
        by_id = self._by_modality.get(modality, {})
        try:
            return by_id[affordance_id]
        except KeyError:
            raise _UnknownAffordanceError(
                f"Affordance {affordance_id!r} not registered for modality {modality!r}"
            )

    def ids_for(self, modality: Modality) -> frozenset[str]:
        return frozenset(self._by_modality.get(modality, {}).keys())
