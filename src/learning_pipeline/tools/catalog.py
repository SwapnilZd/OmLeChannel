"""
ProductionToolCatalog — registry of production tool definitions.

Exposes planner-safe ToolManifests filtered by modality, and provides the
capability → task_type mapping used by ProductionCompiler.

No executor instances, credentials, or provider configuration are stored here.
Manifests are returned in deterministic (lexicographic) order.
"""
from __future__ import annotations

from learning_pipeline.contracts.common import Modality
from learning_pipeline.tools.errors import (
    DuplicateCapabilityError,
    DuplicateTaskTypeError,
    UnsupportedCapabilityError,
)
from learning_pipeline.tools.manifest import ProductionToolDefinition, ToolManifest


class ProductionToolCatalog:
    """Registry of production tool definitions.

    Used by:
    - the Workflow Planner (via ``planner_view``) to discover available capabilities
    - the ProductionCompiler (via ``task_type_for``) to map capabilities to task types
    - the composition root (via ``register``) to add tool definitions at startup
    """

    def __init__(self) -> None:
        self._by_capability: dict[str, ProductionToolDefinition] = {}
        self._task_types: set[str] = set()

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, definition: ProductionToolDefinition) -> None:
        """Register a tool definition.

        Raises ``DuplicateCapabilityError`` if the capability is already present.
        Raises ``DuplicateTaskTypeError`` if the task type is claimed by another.
        """
        cap = definition.manifest.capability
        tt = definition.manifest.task_type
        if cap in self._by_capability:
            raise DuplicateCapabilityError(cap)
        if tt in self._task_types:
            raise DuplicateTaskTypeError(tt)
        self._by_capability[cap] = definition
        self._task_types.add(tt)

    # ── Planner interface ─────────────────────────────────────────────────────

    def resolve_capability(self, capability: str) -> ProductionToolDefinition:
        """Return the full tool definition for a capability.

        Raises ``UnsupportedCapabilityError`` if not registered.
        """
        try:
            return self._by_capability[capability]
        except KeyError as exc:
            raise UnsupportedCapabilityError(capability) from exc

    def manifest_for(self, capability: str) -> ToolManifest:
        """Return the planner-safe manifest for one capability."""
        return self.resolve_capability(capability).manifest

    def manifests_for_modality(self, modality: Modality) -> tuple[ToolManifest, ...]:
        """Return manifests that support the given modality, ordered by capability name."""
        return tuple(
            defn.manifest
            for defn in sorted(
                self._by_capability.values(),
                key=lambda d: d.manifest.capability,
            )
            if modality in defn.manifest.supported_modalities
        )

    def planner_view(self, modality: Modality) -> tuple[ToolManifest, ...]:
        """Return deterministically ordered, planner-safe manifests for a modality."""
        return self.manifests_for_modality(modality)

    # ── Compiler interface ────────────────────────────────────────────────────

    def task_type_for(self, capability: str) -> str:
        """Map a semantic capability name to its runtime task type.

        Used by ``ProductionCompiler``.  Raises ``UnsupportedCapabilityError``
        if the capability is not in the catalog.
        """
        return self.resolve_capability(capability).manifest.task_type

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._by_capability)

    @property
    def task_types(self) -> frozenset[str]:
        return frozenset(self._task_types)
