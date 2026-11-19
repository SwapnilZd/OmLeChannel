"""Source-to-learning authoring services."""

__all__ = ["ObjectiveDiscoveryService", "RLODraftingService", "SourceMappingService"]


def __getattr__(name: str):
    if name == "SourceMappingService":
        from .mapping import SourceMappingService

        return SourceMappingService
    if name == "ObjectiveDiscoveryService":
        from .objectives import ObjectiveDiscoveryService

        return ObjectiveDiscoveryService
    if name == "RLODraftingService":
        from .drafting import RLODraftingService

        return RLODraftingService
    raise AttributeError(name)
