"""
Spoken-duration estimation utilities — Phase 9.

Provides a word-count-based estimator for validating podcast draft timing.
These estimates are intentionally approximate: real TTS duration is measured
from WAV frame counts after execution (Phase 8 audio_utils.wav_duration_seconds).

The estimator is used ONLY for:
  - validation and early-warning checks during planning;
  - reporting estimated duration in planning traces.

It must NOT be used as the final deliverable duration.
"""
from __future__ import annotations


DEFAULT_WORDS_PER_MINUTE = 140
"""
Typical conversational narration pace for professional podcasts.

Published podcast studies suggest 120–180 WPM for clear educational speech.
140 WPM is a conservative mid-range that gives a slight over-estimate to
avoid under-planning time budgets.
"""

DEFAULT_DURATION_TOLERANCE = 0.30
"""
Fractional tolerance applied when comparing an estimated duration to a budget.

A value of 0.30 means a draft is accepted if its estimated duration is within
30% of the permitted budget.  Real speech duration varies with prosody, pauses,
and TTS model behaviour, so hard limits on word-count estimates would be noisy.
"""


def estimate_spoken_seconds(
    text: str,
    *,
    wpm: int = DEFAULT_WORDS_PER_MINUTE,
) -> float:
    """Return the estimated spoken duration of *text* in seconds.

    Uses a simple word-count heuristic: ``word_count / wpm * 60``.

    Args:
        text: The spoken text to estimate.  Whitespace-only strings return 0.0.
        wpm:  Words per minute.  Defaults to ``DEFAULT_WORDS_PER_MINUTE`` (140).

    Raises:
        ValueError: If *wpm* is less than or equal to zero.
    """
    if wpm <= 0:
        raise ValueError(f"wpm must be positive, got {wpm!r}")
    words = len(text.split())
    if words == 0:
        return 0.0
    return words / wpm * 60.0


def estimate_draft_duration_seconds(
    segment_texts: list[str],
    pause_seconds: list[float],
    default_gap_seconds: float = 0.35,
    *,
    wpm: int = DEFAULT_WORDS_PER_MINUTE,
) -> float:
    """Return the total estimated duration for a sequence of segments.

    Applies the same pause policy as ``RealAudioAssemblyExecutor``:
    - Between adjacent segments: ``pause_after + default_gap``
    - After the final segment: ``pause_after`` only (no default gap)

    Args:
        segment_texts:    Spoken text for each segment (in order).
        pause_seconds:    ``pause_after_seconds`` for each segment (same length).
        default_gap_seconds: Gap inserted between adjacent segments.
        wpm: Words per minute for spoken-duration estimation.

    Raises:
        ValueError: If *segment_texts* and *pause_seconds* have different lengths.
    """
    if len(segment_texts) != len(pause_seconds):
        raise ValueError(
            f"segment_texts and pause_seconds must have the same length "
            f"({len(segment_texts)} vs {len(pause_seconds)})"
        )
    if not segment_texts:
        return 0.0

    total = 0.0
    last_idx = len(segment_texts) - 1
    for i, (text, pause) in enumerate(zip(segment_texts, pause_seconds)):
        total += estimate_spoken_seconds(text, wpm=wpm)
        if i < last_idx:
            total += pause + default_gap_seconds
        else:
            total += pause
    return total


def check_duration_budget(
    estimated_seconds: float,
    budget_seconds: float,
    tolerance: float = DEFAULT_DURATION_TOLERANCE,
) -> bool:
    """Return True if *estimated_seconds* is within *tolerance* of *budget_seconds*.

    A draft passes if:
        estimated_seconds <= budget_seconds * (1 + tolerance)

    Args:
        estimated_seconds: Estimated total spoken duration.
        budget_seconds:    Maximum permitted duration (e.g. from learner context).
        tolerance:         Fractional over-budget allowance.  Default 0.30 (30%).
    """
    return estimated_seconds <= budget_seconds * (1.0 + tolerance)
