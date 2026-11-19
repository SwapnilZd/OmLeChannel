"""
Shared Reusable Learning Object (RLO) schema.

Single source of truth for RLO Pydantic models, imported by both the ingestion
API (`api/`) and the slide pipeline (`pipeline/`). Versioned: `v1` is the current
major, and `validate_rlo()` dispatches on a document's `schema_version`.
"""

from .registry import SchemaVersionError, supported_versions, validate_rlo
from .v1 import (
    RLO,
    AssessmentItem,
    AssessmentOption,
    Component,
    Concept,
    DesignBrief,
    EnablingObjective,
    Evidence,
    EvidenceRole,
    GagneEventMapping,
    Misconception,
    Source,
)

__all__ = [
    "RLO",
    "validate_rlo",
    "SchemaVersionError",
    "supported_versions",
    "AssessmentItem",
    "AssessmentOption",
    "Component",
    "Concept",
    "DesignBrief",
    "EnablingObjective",
    "Evidence",
    "EvidenceRole",
    "GagneEventMapping",
    "Misconception",
    "Source",
]
