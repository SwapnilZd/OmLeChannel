"""Shared DAG validation helper used by production and build validators."""

from __future__ import annotations

import heapq

from learning_pipeline.validation.errors import CrossContractValidationError


def validate_dag(
    node_ids: tuple[str, ...],
    dependencies: dict[str, tuple[str, ...]],
    *,
    object_type: str,
) -> None:
    """
    Validate a directed acyclic graph defined by ``node_ids`` and ``dependencies``.

    ``dependencies`` maps a node ID to the IDs of nodes it depends on.  Nodes
    with no dependencies need not appear as keys; missing keys are treated as
    empty dependency lists.

    Rejects:
    - Duplicate node IDs
    - Dependencies that reference unknown nodes
    - Self-dependencies (a node in its own dependency list)
    - Dependency cycles

    Uses deterministic (lexicographic) traversal so results are repeatable
    regardless of insertion order.
    """
    id_set = set(node_ids)

    # Duplicate node IDs
    if len(id_set) != len(node_ids):
        seen: set[str] = set()
        for nid in node_ids:
            if nid in seen:
                raise CrossContractValidationError(
                    "duplicate_id",
                    f"duplicate {object_type} id: '{nid}'",
                    object_id=nid,
                )
            seen.add(nid)

    # Unknown and self-dependencies (deterministic: sorted order)
    for node_id in sorted(node_ids):
        for dep in dependencies.get(node_id, ()):
            if dep == node_id:
                raise CrossContractValidationError(
                    "dependency_cycle",
                    f"{object_type} '{node_id}' depends on itself",
                    object_id=node_id,
                    field="depends_on",
                )
            if dep not in id_set:
                raise CrossContractValidationError(
                    "missing_dependency",
                    f"missing dependency: {object_type} '{node_id}' depends on unknown '{dep}'",
                    object_id=node_id,
                    field="depends_on",
                )

    # Cycle detection via Kahn's algorithm with sorted (deterministic) traversal
    children: dict[str, list[str]] = {nid: [] for nid in node_ids}
    indegree: dict[str, int] = {nid: 0 for nid in node_ids}
    for node_id in node_ids:
        for dep in dependencies.get(node_id, ()):
            children[dep].append(node_id)
            indegree[node_id] += 1

    ready: list[str] = []
    for nid in sorted(node_ids):
        if indegree[nid] == 0:
            heapq.heappush(ready, nid)

    visited = 0
    while ready:
        node_id = heapq.heappop(ready)
        visited += 1
        for child in sorted(children[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)

    if visited != len(node_ids):
        raise CrossContractValidationError(
            "dependency_cycle",
            f"dependency cycle detected in {object_type} dependency graph",
        )
