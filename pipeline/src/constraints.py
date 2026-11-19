"""
Deterministic text-density constraints for slide content.

Slide components declare per-slot budgets in their registry descriptor
(`components/registry/<id>.yaml`): text slots carry `min_chars`/`max_chars`,
array slots carry `min_items`/`max_items` (and optionally `item_max_chars` for
arrays of plain strings, or nested `item_slots` for arrays of objects).

`validate_budgets()` checks an expanded screen's content against its descriptor
and returns a list of `Violation`s — each with a concrete repair message. It is a
pure function with no LLM or I/O, so it is fully deterministic and unit-testable.
The agent layer uses it as the "validate" step of select → fit → validate →
repair: any violation becomes retry feedback for the fitting agent.

Design notes:
- Slot names in the descriptor must match the field names on the ScreenContent
  model (already the project convention).
- Only bounds that are declared are enforced. `min_chars`/`min_items` implement
  the "not too little" floor; `max_chars`/`max_items` the "not too much" ceiling.
- `target_chars` is guidance for prompts, not a hard bound — it is not enforced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Kinds of budget violation.
OVER = "over"          # text longer than max_chars
UNDER = "under"        # text shorter than min_chars
TOO_MANY = "too_many"  # array longer than max_items
TOO_FEW = "too_few"    # array shorter than min_items


@dataclass(frozen=True)
class Violation:
    path: str      # dotted/indexed slot path, e.g. "cards[0].back_definition"
    kind: str      # OVER | UNDER | TOO_MANY | TOO_FEW
    actual: int    # measured length / count
    bound: int     # the bound that was crossed
    message: str   # concrete repair instruction for the fitting agent

    def __str__(self) -> str:
        return self.message


def _text_len(value: Any) -> int:
    if value is None:
        return 0
    return len(str(value).strip())


def _check_text(value: Any, spec: dict, path: str, out: list[Violation]) -> None:
    n = _text_len(value)
    max_chars = spec.get("max_chars")
    min_chars = spec.get("min_chars")
    if max_chars is not None and n > max_chars:
        out.append(Violation(
            path, OVER, n, max_chars,
            f"Shorten '{path}' to at most {max_chars} characters (currently {n}).",
        ))
    if min_chars is not None and n < min_chars:
        out.append(Violation(
            path, UNDER, n, min_chars,
            f"Expand '{path}' to at least {min_chars} characters (currently {n}); add substance, do not pad.",
        ))


def _check_array(value: Any, spec: dict, path: str, out: list[Violation]) -> None:
    items = value if isinstance(value, list) else []
    count = len(items)
    min_items = spec.get("min_items")
    max_items = spec.get("max_items")
    if max_items is not None and count > max_items:
        out.append(Violation(
            path, TOO_MANY, count, max_items,
            f"Use at most {max_items} items in '{path}' (currently {count}).",
        ))
    if min_items is not None and count < min_items:
        out.append(Violation(
            path, TOO_FEW, count, min_items,
            f"Provide at least {min_items} items in '{path}' (currently {count}).",
        ))

    item_slots = spec.get("item_slots")
    item_max_chars = spec.get("item_max_chars")
    for i, item in enumerate(items):
        item_path = f"{path}[{i}]"
        if item_slots:
            if isinstance(item, dict):
                _check_slots(item_slots, item, item_path, out)
            elif set(item_slots) == {"text"}:
                # Registry descriptors use ``item_slots.text`` for arrays whose
                # Pydantic field is list[str] (for example, objectives and
                # skills_reinforced). Treat the scalar item as that text slot.
                _check_text(item, item_slots["text"], item_path, out)
        elif item_max_chars is not None:
            _check_text(item, {"max_chars": item_max_chars, "min_chars": spec.get("item_min_chars")}, item_path, out)


def _is_array_spec(spec: dict) -> bool:
    return spec.get("type") == "array" or "item_slots" in spec or "min_items" in spec or "max_items" in spec


def _is_object_spec(spec: dict) -> bool:
    return spec.get("type") == "object" or "slots" in spec


def _check_slots(slots: dict, data: dict, prefix: str, out: list[Violation]) -> None:
    for name, spec in slots.items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}.{name}" if prefix else name
        value = data.get(name) if isinstance(data, dict) else None
        if _is_array_spec(spec):
            _check_array(value, spec, path, out)
        elif _is_object_spec(spec):
            _check_slots(spec.get("slots", {}), value if isinstance(value, dict) else {}, path, out)
        else:
            _check_text(value, spec, path, out)


def _derive_min(slots: dict, ratio: float) -> dict:
    """
    Return a copy of `slots` with `min_chars` filled from `target_chars * ratio`
    (rounded) wherever a text slot declares a target but no explicit floor. An
    explicit `min_chars` is never overridden. Recurses into `item_slots`.
    """
    out: dict = {}
    for name, spec in slots.items():
        if not isinstance(spec, dict):
            out[name] = spec
            continue
        spec = dict(spec)
        if "item_slots" in spec and isinstance(spec["item_slots"], dict):
            spec["item_slots"] = _derive_min(spec["item_slots"], ratio)
        if "slots" in spec and isinstance(spec["slots"], dict):
            spec["slots"] = _derive_min(spec["slots"], ratio)
        is_text = not _is_array_spec(spec) and not _is_object_spec(spec)
        if is_text and spec.get("min_chars") is None and spec.get("target_chars"):
            spec["min_chars"] = round(spec["target_chars"] * ratio)
        out[name] = spec
    return out


def validate_budgets(
    content: dict,
    descriptor: dict,
    *,
    min_char_floor_ratio: float | None = None,
) -> list[Violation]:
    """
    Validate expanded screen `content` (a plain dict, e.g. ScreenContent.model_dump())
    against a component `descriptor` (parsed registry YAML). Returns all violations;
    an empty list means the content fits its budgets.

    By default only declared bounds are enforced. Pass `min_char_floor_ratio`
    (e.g. 0.4) to derive a "not too little" floor from each slot's `target_chars`
    where no explicit `min_chars` is set — giving density-floor enforcement
    repo-wide without editing every descriptor. Explicit `min_chars` always wins.
    """
    slots = descriptor.get("slots") or {}
    if min_char_floor_ratio is not None:
        slots = _derive_min(slots, min_char_floor_ratio)
    out: list[Violation] = []
    _check_slots(slots, content, "", out)
    return out


def format_violations(violations: list[Violation]) -> str:
    """Render violations as a numbered repair brief for an agent retry prompt."""
    if not violations:
        return ""
    lines = ["The content does not fit the slide's density budget. Fix these and resubmit:"]
    lines += [f"{i}. {v.message}" for i, v in enumerate(violations, 1)]
    return "\n".join(lines)
