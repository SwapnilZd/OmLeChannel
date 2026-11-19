"""Governance policy enforcement — Phase 12."""
from __future__ import annotations

from learning_pipeline.contracts.curriculum_assembly import (
    AssemblyRLOCandidate,
    CourseAssemblyRequest,
)
from learning_pipeline.contracts.rlo import RLODocument

APPROVED_GOVERNANCE_STATUSES: frozenset[str] = frozenset({"approved", "active"})

GOVERNANCE_POLICY_VERSION = "governance_v1"


class GovernanceViolationError(RuntimeError):
    """Raised when a required candidate is prohibited by governance policy."""

    def __init__(self, rlo_id: str, version: str, status: str) -> None:
        super().__init__(
            f"RLO '{rlo_id}' v{version} is required but has governance status "
            f"'{status}' which is not in the approved set {sorted(APPROVED_GOVERNANCE_STATUSES)}."
        )
        self.rlo_id = rlo_id
        self.version = version
        self.status = status


def is_governance_approved(rlo: RLODocument) -> bool:
    """Return True if the RLO is approved for use in assembly."""
    return rlo.governance.status in APPROVED_GOVERNANCE_STATUSES


def enforce_governance(
    candidates: tuple[AssemblyRLOCandidate, ...],
    rlos: dict[str, RLODocument],
    request: CourseAssemblyRequest,
) -> tuple[set[str], list[str]]:
    """Check governance for every candidate.

    Returns:
        (rejected_rlo_ids, governance_warnings)

    Raises:
        GovernanceViolationError — if a *required* candidate is governance-rejected.
    """
    required_ids = set(request.constraints.required_rlo_ids)
    rejected: set[str] = set()
    warnings: list[str] = []

    for candidate in candidates:
        rlo = rlos.get(candidate.rlo_id)
        if rlo is None:
            continue
        if not is_governance_approved(rlo):
            if candidate.rlo_id in required_ids:
                raise GovernanceViolationError(
                    candidate.rlo_id, candidate.rlo_version, rlo.governance.status
                )
            rejected.add(candidate.rlo_id)
            warnings.append(
                f"RLO '{candidate.rlo_id}' v{candidate.rlo_version} excluded: "
                f"governance status '{rlo.governance.status}' is not approved."
            )

    return rejected, warnings
