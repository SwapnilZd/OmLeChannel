"""Prerequisite ordering validation — Phase 12."""
from __future__ import annotations

from learning_pipeline.contracts.common import TopicProficiency, PROFICIENCY_ORDER
from learning_pipeline.contracts.curriculum_assembly import (
    CourseAssemblyDraft,
    CourseAssemblyRequest,
    PrerequisiteBridge,
    RLOAssemblyContext,
    TailoredRLODraft,
)
from learning_pipeline.contracts.learner import LearnerContext


class PrerequisiteViolationError(ValueError):
    """Raised when the draft ordering violates a dependency constraint."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class DependencyCycleError(ValueError):
    """Raised when a dependency cycle is detected among candidate RLOs."""

    def __init__(self, cycle: list[str]) -> None:
        super().__init__(f"Dependency cycle detected: {' -> '.join(cycle)}")
        self.cycle = cycle


def _detect_cycles(
    included_ids: set[str],
    prereq_map: dict[str, list[str]],
) -> None:
    """Raise DependencyCycleError if there is a cycle in the included RLO set."""
    visited: set[str] = set()
    in_stack: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> None:
        visited.add(node)
        in_stack.add(node)
        stack.append(node)
        for dep in prereq_map.get(node, []):
            if dep not in included_ids:
                continue
            if dep not in visited:
                dfs(dep)
            elif dep in in_stack:
                cycle_start = stack.index(dep)
                raise DependencyCycleError(stack[cycle_start:] + [dep])
        stack.pop()
        in_stack.discard(node)

    for rlo_id in included_ids:
        if rlo_id not in visited:
            dfs(rlo_id)


def _learner_already_knows(learner: LearnerContext, prerequisite_topic: str) -> bool:
    """Return True if the learner's proficiency demonstrates the prerequisite is met."""
    proficiency = learner.topic_proficiencies.get(prerequisite_topic)
    if proficiency is None:
        proficiency = learner.default_proficiency
    return PROFICIENCY_ORDER[proficiency] >= PROFICIENCY_ORDER[TopicProficiency.INTERMEDIATE]


def validate_prerequisite_ordering(
    draft: CourseAssemblyDraft,
    contexts: dict[str, RLOAssemblyContext],
    request: CourseAssemblyRequest,
) -> list[str]:
    """Validate prerequisite ordering and bridges.

    Returns a list of informational prerequisite findings (non-fatal).

    Raises:
        DependencyCycleError — on a cycle in the dependency graph.
        PrerequisiteViolationError — on an ordering violation without a valid resolution.
    """
    included_ids: set[str] = {d.rlo_id for d in draft.ordered_rlo_drafts}
    order_map: dict[str, int] = {d.rlo_id: d.order for d in draft.ordered_rlo_drafts}
    bridge_covers: dict[str, list[PrerequisiteBridge]] = {}
    for bridge in draft.prerequisite_bridges:
        bridge_covers.setdefault(bridge.before_rlo_id, []).append(bridge)

    # Build prerequisite map from RLO metadata
    prereq_map: dict[str, list[str]] = {}
    for rlo_id, ctx in contexts.items():
        prereq_map[rlo_id] = list(ctx.prerequisites)

    # Detect cycles in included set
    _detect_cycles(included_ids, prereq_map)

    findings: list[str] = []

    for draft_ref in draft.ordered_rlo_drafts:
        rlo_id = draft_ref.rlo_id
        ctx = contexts.get(rlo_id)
        if ctx is None:
            continue
        for prereq_id in ctx.prerequisites:
            if prereq_id in included_ids:
                # Prerequisite is included — verify ordering
                if order_map.get(prereq_id, 0) >= order_map[rlo_id]:
                    raise PrerequisiteViolationError(
                        f"Prerequisite '{prereq_id}' must appear before '{rlo_id}' "
                        f"(orders: {order_map.get(prereq_id)} >= {order_map[rlo_id]})"
                    )
                findings.append(
                    f"Prerequisite '{prereq_id}' correctly precedes '{rlo_id}'."
                )
            else:
                # Prerequisite is omitted — need bridge or learner proficiency waiver
                prereq_ctx = contexts.get(prereq_id)
                prereq_topic = prereq_ctx.topic if prereq_ctx else prereq_id

                covers = bridge_covers.get(rlo_id, [])
                has_bridge = any(
                    b.prerequisite_topic == prereq_topic or b.prerequisite_topic == prereq_id
                    for b in covers
                )
                if has_bridge:
                    findings.append(
                        f"Prerequisite '{prereq_id}' for '{rlo_id}' covered by bridge."
                    )
                    continue

                if _learner_already_knows(request.learner, prereq_topic):
                    findings.append(
                        f"Prerequisite '{prereq_id}' for '{rlo_id}' waived: learner "
                        f"has sufficient proficiency for topic '{prereq_topic}'."
                    )
                    continue

                raise PrerequisiteViolationError(
                    f"RLO '{rlo_id}' has prerequisite '{prereq_id}' which is omitted "
                    f"from the blueprint. Provide a PrerequisiteBridge or confirm "
                    f"learner already has proficiency for '{prereq_topic}'."
                )

    return findings
