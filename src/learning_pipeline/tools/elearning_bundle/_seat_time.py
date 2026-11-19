"""Deterministic learner seat-time estimate for a finished course structure."""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any


SEAT_TIME_POLICY_VERSION = "elearning-seat-time-v1"

_WORDS_PER_MINUTE = 350
_NAVIGATION_SECONDS_PER_SCREEN = 3
_SCREEN_INTERACTION_SECONDS: dict[str, int] = {
    "knowledge_check": 20,
    "reflection_prompt": 15,
    "concept_flip_card": 10,
    "tabbed_content": 10,
    "disclosure_list": 10,
    "scenario_setup": 15,
    "scenario_branch": 15,
    # Until rendered media duration is available at final assembly, reserve a
    # conservative minute for each planned video rather than ignoring it.
    "video_slot": 60,
    "video_player": 60,
}
_NON_LEARNER_FIELDS = frozenset(
    {
        "screen_id",
        "type",
        "sequence",
        "rlo_source_refs",
        "source_scene_ids",
        "slot_id",
        "question_id",
        "branch_id",
        "resolution_screen_id",
        "correct",
        "image_prompt",
        "icon",
    }
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


def _learner_facing_strings(value: Any, *, parent_key: str = "") -> Iterable[str]:
    if parent_key in _NON_LEARNER_FIELDS:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            # Existing duration metadata is model-authored and therefore cannot
            # be an input to its deterministic replacement.
            if key == "metadata":
                child = {
                    item_key: item_value
                    for item_key, item_value in child.items()
                    if item_key not in {"duration", "duration_minutes"}
                }
            yield from _learner_facing_strings(child, parent_key=key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _learner_facing_strings(child, parent_key=parent_key)


def estimate_seat_time_minutes(screens: list[dict[str, Any]]) -> int:
    """Return a stable whole-minute estimate from publishable course content."""
    word_count = sum(
        len(_WORD_RE.findall(text))
        for screen in screens
        for text in _learner_facing_strings(screen)
    )
    reading_seconds = (word_count / _WORDS_PER_MINUTE) * 60
    navigation_seconds = max(len(screens) - 1, 0) * _NAVIGATION_SECONDS_PER_SCREEN
    interaction_seconds = sum(
        _SCREEN_INTERACTION_SECONDS.get(str(screen.get("type", "")), 0)
        for screen in screens
    )
    total_seconds = reading_seconds + navigation_seconds + interaction_seconds
    return max(1, math.ceil(total_seconds / 60))


def apply_seat_time_metadata(screens: list[dict[str, Any]]) -> int:
    """Overwrite model-authored title duration with the deterministic estimate."""
    minutes = estimate_seat_time_minutes(screens)
    for screen in screens:
        if screen.get("type") != "title":
            continue
        metadata = dict(screen.get("metadata") or {})
        metadata["duration_minutes"] = minutes
        metadata["duration"] = f"About {minutes} minute{'s' if minutes != 1 else ''}"
        screen["metadata"] = metadata
        break
    return minutes
