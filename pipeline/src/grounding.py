"""Strict, content-agnostic source grounding for v1 RLOs."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from rlo_schema import RLO

_TOKEN = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)|\[(?P<index>0|[1-9][0-9]*)\]")


class SourceReferenceError(ValueError):
    """Raised when a plan references content that does not exist in the RLO."""


def _tokens(path: str) -> list[str | int]:
    if not path:
        raise SourceReferenceError("RLO source reference cannot be empty.")
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[(?:0|[1-9][0-9]*)\]))*",
        path,
    ):
        raise SourceReferenceError(f"Malformed RLO source reference {path!r}.")
    tokens: list[str | int] = []
    position = 0
    while position < len(path):
        match = _TOKEN.match(path, position)
        if match is None:
            if path[position] == "." and position > 0:
                position += 1
                continue
            raise SourceReferenceError(
                f"Malformed RLO source reference {path!r} at character {position}."
            )
        tokens.append(
            int(match.group("index"))
            if match.group("index") is not None
            else match.group("name")
        )
        position = match.end()
    return tokens


def resolve_rlo_ref(rlo: RLO | BaseModel | dict[str, Any], path: str) -> Any:
    """Resolve one dotted/indexed path or raise :class:`SourceReferenceError`."""
    cursor: Any = rlo.model_dump(mode="json") if isinstance(rlo, BaseModel) else rlo
    for token in _tokens(path):
        if isinstance(token, str) and isinstance(cursor, dict):
            if token not in cursor:
                raise SourceReferenceError(
                    f"RLO source reference {path!r} has no field {token!r}."
                )
            cursor = cursor[token]
        elif isinstance(token, int) and isinstance(cursor, list):
            if token >= len(cursor):
                raise SourceReferenceError(
                    f"RLO source reference {path!r} index {token} is out of range."
                )
            cursor = cursor[token]
        else:
            raise SourceReferenceError(
                f"RLO source reference {path!r} cannot apply {token!r} to "
                f"{type(cursor).__name__}."
            )
    return cursor


def resolve_rlo_refs(rlo: RLO, refs: list[str]) -> dict[str, Any]:
    """Resolve source references while retaining their exact paths as keys."""
    if not refs:
        raise SourceReferenceError("Every screen must declare at least one RLO source reference.")
    return {ref: resolve_rlo_ref(rlo, ref) for ref in refs}
