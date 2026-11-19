"""Deterministic validation and traversal for extracted document trees."""

from __future__ import annotations

import uuid
from typing import Any

from .contracts import DocumentNode, ExtractedDocument


class HierarchyError(ValueError):
    pass


NODE_ID_NAMESPACE = uuid.UUID("87c92f38-8bd5-4f9e-88c6-902dde8f4678")


def stable_node_id(
    source_version_id: str,
    *,
    kind: str,
    ordinal_path: tuple[int, ...],
) -> str:
    identity = f"{source_version_id}:{kind}:{'.'.join(map(str, ordinal_path))}"
    return str(uuid.uuid5(NODE_ID_NAMESPACE, identity))


def validate_document(document: ExtractedDocument) -> ExtractedDocument:
    by_id = {node.node_id: node for node in document.nodes}
    if len(by_id) != len(document.nodes):
        raise HierarchyError("duplicate node ID")

    derived_children: dict[str | None, list[DocumentNode]] = {}
    for node in document.nodes:
        if node.parent_id is not None and node.parent_id not in by_id:
            raise HierarchyError(f"orphaned node: {node.node_id}")
        derived_children.setdefault(node.parent_id, []).append(node)

    roots = derived_children.get(None, [])
    if not roots:
        raise HierarchyError("document has no root node")

    for node in document.nodes:
        ancestors: set[str] = set()
        cursor = node
        while cursor.parent_id is not None:
            if cursor.node_id in ancestors:
                raise HierarchyError(f"cycle at {cursor.node_id}")
            ancestors.add(cursor.node_id)
            cursor = by_id[cursor.parent_id]

    for parent_id, siblings in derived_children.items():
        ordinals = [node.ordinal for node in siblings]
        if len(ordinals) != len(set(ordinals)):
            raise HierarchyError(f"duplicate sibling ordinal under {parent_id}")
        siblings.sort(key=lambda node: node.ordinal)
        if parent_id is not None:
            expected = [node.node_id for node in siblings]
            if by_id[parent_id].child_ids != expected:
                raise HierarchyError(f"mismatched child list for {parent_id}")

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: DocumentNode, path: tuple[int, ...]) -> None:
        if node.node_id in active:
            raise HierarchyError(f"cycle at {node.node_id}")
        if node.node_id in visited:
            raise HierarchyError(f"node appears more than once: {node.node_id}")
        if node.ordinal_path != path:
            raise HierarchyError(f"invalid ordinal path for {node.node_id}")
        active.add(node.node_id)
        visited.add(node.node_id)
        for child in derived_children.get(node.node_id, []):
            visit(child, path + (child.ordinal,))
        active.remove(node.node_id)

    for root in sorted(roots, key=lambda node: node.ordinal):
        visit(root, (root.ordinal,))
    if visited != set(by_id):
        raise HierarchyError("not all nodes are reachable")

    relationship_ids: set[str] = set()
    for relationship in document.relationships:
        if relationship.relationship_id in relationship_ids:
            raise HierarchyError("duplicate relationship ID")
        relationship_ids.add(relationship.relationship_id)
        if relationship.source_node_id not in by_id or relationship.target_node_id not in by_id:
            raise HierarchyError(f"invalid relationship: {relationship.relationship_id}")

    extent = (
        document.page_count or document.slide_count or document.chapter_count or 0
    )
    for node in document.nodes:
        for locator in node.locators:
            position = locator.page or locator.slide or locator.chapter or 0
            if position > extent:
                raise HierarchyError(f"locator outside source for {node.node_id}")
            if document.page_count and locator.page is None:
                raise HierarchyError(f"slide locator in PDF node {node.node_id}")
            if document.slide_count and locator.slide is None:
                raise HierarchyError(f"page locator in PPTX node {node.node_id}")
            if document.chapter_count and locator.chapter is None:
                raise HierarchyError(f"non-chapter locator in EPUB node {node.node_id}")
    return document


def depth_first_nodes(document: ExtractedDocument) -> list[DocumentNode]:
    validate_document(document)
    return sorted(document.nodes, key=lambda node: node.ordinal_path)


def nested_view(document: ExtractedDocument) -> list[dict[str, Any]]:
    ordered = depth_first_nodes(document)
    by_parent: dict[str | None, list[DocumentNode]] = {}
    for node in ordered:
        by_parent.setdefault(node.parent_id, []).append(node)

    def nest(node: DocumentNode) -> dict[str, Any]:
        value = node.model_dump(mode="json")
        value["children"] = [nest(child) for child in by_parent.get(node.node_id, [])]
        return value

    return [nest(root) for root in by_parent.get(None, [])]


def adjacency_from_nested(roots: list[dict[str, Any]]) -> list[DocumentNode]:
    nodes: list[DocumentNode] = []

    def flatten(value: dict[str, Any]) -> None:
        node_value = dict(value)
        children = node_value.pop("children", [])
        nodes.append(DocumentNode.model_validate(node_value))
        for child in children:
            flatten(child)

    for root in roots:
        flatten(root)
    return nodes
