"""Deterministic adapters into downstream learning-pipeline contracts."""

from .assembly import (
    ASSEMBLY_ADAPTER_POLICY_VERSION,
    AssemblyAdapterError,
    AssemblyAdapterResult,
    AssemblyAdapterTrace,
    build_course_assembly_request,
    project_audience_to_learner,
)
from .rlo import RLOCompatibilityError, adapt_stored_rlo

__all__ = [
    "ASSEMBLY_ADAPTER_POLICY_VERSION",
    "AssemblyAdapterError",
    "AssemblyAdapterResult",
    "AssemblyAdapterTrace",
    "RLOCompatibilityError",
    "adapt_stored_rlo",
    "build_course_assembly_request",
    "project_audience_to_learner",
]
