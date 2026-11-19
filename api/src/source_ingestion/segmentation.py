"""Hierarchy-first source segmentation and shared source-token budgeting."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field

import tiktoken

from .contracts import DocumentNode, ExtractedDocument, SourceSegment
from .hierarchy import depth_first_nodes


DEFAULT_SEGMENT_TOKENS = 1_200
DEFAULT_OVERLAP_TOKENS = 100
DEFAULT_SOURCE_TRANCHE_TOKEN_LIMIT = 15_000
DEFAULT_SOURCE_REQUEST_TOKEN_LIMIT = 100_000
SOURCE_TRANCHE_TOKEN_LIMIT_ENV = "SOURCE_CONTENT_TRANCHE_TOKEN_LIMIT"
SOURCE_REQUEST_TOKEN_LIMIT_ENV = "SOURCE_CONTENT_REQUEST_TOKEN_LIMIT"
SEGMENT_ID_NAMESPACE = uuid.UUID("80899de0-51b4-4dab-98de-90aa6b11720c")
HEADING_KINDS = {"title", "section_header", "heading", "chapter", "slide_title"}
TABLE_KINDS = {"table"}


class TokenBudgetExceeded(ValueError):
    pass


def _configured_token_limit(name: str, default: int) -> int:
    raw_limit = os.environ.get(name, str(default))
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if limit < 1:
        raise ValueError(f"{name} must be positive")
    return limit


def configured_source_tranche_token_limit() -> int:
    return _configured_token_limit(
        SOURCE_TRANCHE_TOKEN_LIMIT_ENV, DEFAULT_SOURCE_TRANCHE_TOKEN_LIMIT
    )


def configured_source_request_token_limit() -> int:
    return _configured_token_limit(
        SOURCE_REQUEST_TOKEN_LIMIT_ENV, DEFAULT_SOURCE_REQUEST_TOKEN_LIMIT
    )


@dataclass(frozen=True)
class SourceTokenBudget:
    source_token_limit: int = field(
        default_factory=configured_source_tranche_token_limit
    )
    request_token_limit: int = field(
        default_factory=configured_source_request_token_limit
    )
    encoding_name: str = "o200k_base"

    def __post_init__(self) -> None:
        if self.source_token_limit < 1:
            raise ValueError("source tranche token limit must be positive")
        if self.request_token_limit < self.source_token_limit:
            raise ValueError(
                "source request token limit must be at least the tranche token limit"
            )

    @property
    def encoding(self):
        return tiktoken.get_encoding(self.encoding_name)

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def require_within_limit(
        self,
        text: str,
        *,
        complete_request_limit: int | None = None,
        reserved_tokens: int = 0,
    ) -> int:
        effective_limit = self.request_token_limit
        if complete_request_limit is not None:
            effective_limit = min(effective_limit, complete_request_limit - reserved_tokens)
        if effective_limit < 1:
            raise TokenBudgetExceeded("no source-token capacity remains after reservations")
        count = self.count(text)
        if count > effective_limit:
            raise TokenBudgetExceeded(
                f"source content uses {count} tokens; limit is {effective_limit}"
            )
        return count


def _hierarchy_path(node: DocumentNode, by_id: dict[str, DocumentNode]) -> list[str]:
    path = [node.node_id]
    while node.parent_id is not None:
        node = by_id[node.parent_id]
        path.append(node.node_id)
    return list(reversed(path))


def _common_hierarchy_path(
    nodes: list[DocumentNode], by_id: dict[str, DocumentNode]
) -> list[str]:
    paths = [_hierarchy_path(node, by_id) for node in nodes]
    common = []
    for values in zip(*paths):
        if len(set(values)) != 1:
            break
        common.append(values[0])
    return common or [paths[0][0]]


def _segment_id(
    source_version_id: str, ordinal: int, node_ids: list[str], text: str
) -> str:
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    identity = f"{source_version_id}:{ordinal}:{','.join(node_ids)}:{text_hash}"
    return str(uuid.uuid5(SEGMENT_ID_NAMESPACE, identity))


def _is_markdown_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _table_chunks(text: str, encoding, max_tokens: int) -> list[str]:
    """Split a serialized table by rows and repeat its header where it fits."""

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        tokens = encoding.encode(text)
        return [
            encoding.decode(tokens[start : start + max_tokens]).strip()
            for start in range(0, len(tokens), max_tokens)
        ]

    header_count = 2 if _is_markdown_table_separator(lines[1]) else 1
    header = "\n".join(lines[:header_count])
    rows = lines[header_count:]
    header_tokens = encoding.encode(header)
    chunks: list[str] = []
    current_rows: list[str] = []

    def render(values: list[str], *, include_header: bool = True) -> str:
        parts = [header] if include_header else []
        parts.extend(values)
        return "\n".join(parts)

    def flush() -> None:
        nonlocal current_rows
        if current_rows:
            chunks.append(render(current_rows))
            current_rows = []

    for row in rows:
        candidate = render([*current_rows, row])
        if len(encoding.encode(candidate)) <= max_tokens:
            current_rows.append(row)
            continue
        flush()
        with_header = render([row])
        if len(encoding.encode(with_header)) <= max_tokens:
            current_rows = [row]
            continue
        row_tokens = encoding.encode(row)
        available = max_tokens - len(header_tokens) - 1
        include_header = available > 0
        width = available if include_header else max_tokens
        for start in range(0, len(row_tokens), width):
            piece = encoding.decode(row_tokens[start : start + width]).strip()
            chunks.append(render([piece], include_header=include_header))
    flush()
    return chunks or [header]


def build_source_segment(
    document: ExtractedDocument,
    nodes: list[DocumentNode],
    text: str,
    *,
    ordinal: int,
    encoding,
    split_from_node: bool = False,
) -> SourceSegment:
    node_ids = list(dict.fromkeys(node.node_id for node in nodes))
    return SourceSegment(
        segment_id=_segment_id(document.source_version_id, ordinal, node_ids, text),
        source_version_id=document.source_version_id,
        extraction_run_id=document.extraction_run_id,
        ordinal=ordinal,
        node_ids=node_ids,
        hierarchy_path=_common_hierarchy_path(
            nodes, {node.node_id: node for node in document.nodes}
        ),
        locator_start=nodes[0].locators[0],
        locator_end=nodes[-1].locators[-1],
        token_count=len(encoding.encode(text)),
        text=text,
        split_from_node=split_from_node,
    )


def resequence_segments(
    document: ExtractedDocument, segments: list[SourceSegment]
) -> list[SourceSegment]:
    encoding = tiktoken.get_encoding("o200k_base")
    nodes = {node.node_id: node for node in document.nodes}
    return [
        build_source_segment(
            document,
            [nodes[node_id] for node_id in segment.node_ids],
            segment.text,
            ordinal=ordinal,
            encoding=encoding,
            split_from_node=segment.split_from_node,
        )
        for ordinal, segment in enumerate(segments)
    ]


def segment_document(
    document: ExtractedDocument,
    *,
    max_tokens: int = DEFAULT_SEGMENT_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    budget: SourceTokenBudget | None = None,
    include_node_ids: set[str] | None = None,
) -> list[SourceSegment]:
    if max_tokens < 2:
        raise ValueError("max_tokens must be at least 2")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than max_tokens")
    budget = budget or SourceTokenBudget()
    encoding = budget.encoding
    ordered = [
        node
        for node in depth_first_nodes(document)
        if node.text
        and node.text.strip()
        and (include_node_ids is None or node.node_id in include_node_ids)
    ]
    segments: list[SourceSegment] = []
    pending: list[DocumentNode] = []

    def append(nodes: list[DocumentNode], text: str, *, split_from_node: bool = False) -> None:
        segments.append(
            build_source_segment(
                document,
                nodes,
                text,
                ordinal=len(segments),
                encoding=encoding,
                split_from_node=split_from_node,
            )
        )

    def flush() -> None:
        nonlocal pending
        if pending:
            append(pending, "\n\n".join(node.text.strip() for node in pending))
            pending = []

    for node in ordered:
        text = node.text.strip()
        tokens = encoding.encode(text)
        if len(tokens) > max_tokens:
            flush()
            if node.kind in TABLE_KINDS:
                for chunk in _table_chunks(text, encoding, max_tokens):
                    append([node], chunk, split_from_node=True)
                continue
            step = max_tokens - overlap_tokens
            for start in range(0, len(tokens), step):
                chunk = tokens[start : start + max_tokens]
                if not chunk:
                    break
                append([node], encoding.decode(chunk).strip(), split_from_node=True)
                if start + max_tokens >= len(tokens):
                    break
            continue
        if node.kind in HEADING_KINDS:
            flush()
        candidate = [*pending, node]
        candidate_text = "\n\n".join(item.text.strip() for item in candidate)
        if pending and len(encoding.encode(candidate_text)) > max_tokens:
            flush()
            candidate = [node]
        pending = candidate
    flush()
    return segments
