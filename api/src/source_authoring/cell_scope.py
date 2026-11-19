"""Deterministic Content-Type × Bloom scope for POC2 authoring."""

from __future__ import annotations


POC2_CELLS = (
    ("fact", "remember"),
    ("concept", "understand"),
    ("concept", "apply"),
    ("process", "understand"),
    ("procedure", "apply"),
)

POC2_CELL_SET = frozenset(POC2_CELLS)


def cell_key(content_type: object, bloom_level: object) -> tuple[str, str]:
    return (
        str(getattr(content_type, "value", content_type)),
        str(getattr(bloom_level, "value", bloom_level)),
    )


def is_poc2_cell(content_type: object, bloom_level: object) -> bool:
    return cell_key(content_type, bloom_level) in POC2_CELL_SET


def poc2_scope_reason(content_type: object, bloom_level: object) -> str:
    content, bloom = cell_key(content_type, bloom_level)
    return (
        f"{content} × {bloom} is outside the five Content-Type × Bloom cells "
        "approved for POC2 authoring."
    )


def candidate_scope_error(candidate: object) -> str | None:
    status = str(getattr(candidate, "poc2_scope_status", "needs_review"))
    reason = getattr(candidate, "poc2_scope_reason", None)
    classification = getattr(candidate, "classification", None)
    if status != "supported":
        return reason or "The objective does not have a supported POC2 classification."
    if classification is None:
        return "The objective does not have a supported POC2 classification."
    kind = classification.content_kind.value
    bloom = classification.bloom.value
    if not is_poc2_cell(kind, bloom):
        return poc2_scope_reason(kind, bloom)
    return None


def authoring_scope_error(authoring: object | None) -> str | None:
    if authoring is None:
        return None
    classifications = getattr(authoring, "classifications", None)
    if classifications is None:
        return None
    target = classifications.target
    if not is_poc2_cell(target.content_type, target.bloom_level):
        return poc2_scope_reason(target.content_type, target.bloom_level)
    return None
