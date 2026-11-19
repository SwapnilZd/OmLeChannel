"""Curriculum Assembly — Phase 12.

Public surface for the curriculum assembly subsystem.
"""
from __future__ import annotations

from .agent import (
    PROMPT_VERSION,
    CurriculumAssemblyAgent,
    FakeCurriculumAssemblyAgent,
    LiteLLMCurriculumAssemblyAgent,
)
from .builder import BlueprintBuildError, build_blueprint
from .content_closure import ContentClosureError, validate_and_close_selection
from .context import (
    ContextBudgetExceededError,
    RLOAssemblyContext,
    build_assembly_context,
    check_context_budget,
    serialized_context_size,
)
from .draft_validation import DraftValidationError, validate_draft
from .duration import (
    DURATION_POLICY_VERSION,
    estimate_rlo_duration,
    estimate_total_duration,
)
from .governance import (
    APPROVED_GOVERNANCE_STATUSES,
    GOVERNANCE_POLICY_VERSION,
    GovernanceViolationError,
    enforce_governance,
    is_governance_approved,
)
from .prerequisites import (
    DependencyCycleError,
    PrerequisiteViolationError,
    validate_prerequisite_ordering,
)
from .proficiency import (
    PROFICIENCY_POLICY_VERSION,
    derive_starting_proficiency,
)
from .service import CourseAssemblyError, CourseAssemblyService

__all__ = [
    # Agent
    "PROMPT_VERSION",
    "CurriculumAssemblyAgent",
    "FakeCurriculumAssemblyAgent",
    "LiteLLMCurriculumAssemblyAgent",
    # Builder
    "BlueprintBuildError",
    "build_blueprint",
    # Content closure
    "ContentClosureError",
    "validate_and_close_selection",
    # Context
    "ContextBudgetExceededError",
    "RLOAssemblyContext",
    "build_assembly_context",
    "check_context_budget",
    "serialized_context_size",
    # Draft validation
    "DraftValidationError",
    "validate_draft",
    # Duration
    "DURATION_POLICY_VERSION",
    "estimate_rlo_duration",
    "estimate_total_duration",
    # Governance
    "APPROVED_GOVERNANCE_STATUSES",
    "GOVERNANCE_POLICY_VERSION",
    "GovernanceViolationError",
    "enforce_governance",
    "is_governance_approved",
    # Prerequisites
    "DependencyCycleError",
    "PrerequisiteViolationError",
    "validate_prerequisite_ordering",
    # Proficiency
    "PROFICIENCY_POLICY_VERSION",
    "derive_starting_proficiency",
    # Service
    "CourseAssemblyError",
    "CourseAssemblyService",
]
