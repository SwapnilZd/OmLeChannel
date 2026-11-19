"""Tests for learning_pipeline.duration — Phase 9."""
from __future__ import annotations

import pytest

from learning_pipeline.duration import (
    DEFAULT_DURATION_TOLERANCE,
    DEFAULT_WORDS_PER_MINUTE,
    check_duration_budget,
    estimate_draft_duration_seconds,
    estimate_spoken_seconds,
)


class TestEstimateSpokenSeconds:
    def test_empty_string_returns_zero(self) -> None:
        assert estimate_spoken_seconds("") == 0.0

    def test_whitespace_only_returns_zero(self) -> None:
        assert estimate_spoken_seconds("   \t\n") == 0.0

    def test_single_word(self) -> None:
        assert estimate_spoken_seconds("hello") == pytest.approx(60.0 / 140)

    def test_140_words_takes_60_seconds(self) -> None:
        text = " ".join(["word"] * 140)
        assert estimate_spoken_seconds(text) == pytest.approx(60.0)

    def test_custom_wpm(self) -> None:
        text = "word " * 70
        result = estimate_spoken_seconds(text, wpm=70)
        assert result == pytest.approx(60.0)

    def test_zero_wpm_raises(self) -> None:
        with pytest.raises(ValueError, match="wpm must be positive"):
            estimate_spoken_seconds("hello", wpm=0)

    def test_negative_wpm_raises(self) -> None:
        with pytest.raises(ValueError, match="wpm must be positive"):
            estimate_spoken_seconds("hello", wpm=-10)

    def test_default_wpm_matches_constant(self) -> None:
        text = "word " * DEFAULT_WORDS_PER_MINUTE
        expected = 60.0
        assert estimate_spoken_seconds(text) == pytest.approx(expected)


class TestEstimateDraftDuration:
    def test_single_segment_no_pause(self) -> None:
        texts = ["word " * 140]
        pauses = [0.0]
        result = estimate_draft_duration_seconds(texts, pauses)
        assert result == pytest.approx(60.0)

    def test_single_segment_with_pause_after(self) -> None:
        texts = ["word " * 140]
        pauses = [1.5]
        result = estimate_draft_duration_seconds(texts, pauses)
        assert result == pytest.approx(61.5)

    def test_two_segments_gap_added_between_not_after(self) -> None:
        texts = ["word " * 140, "word " * 140]
        pauses = [0.5, 0.0]
        # Segment 1: 60s + pause(0.5) + default_gap(0.35) between
        # Segment 2: 60s + pause(0.0) — no default_gap after last
        expected = 60.0 + 0.5 + 0.35 + 60.0
        result = estimate_draft_duration_seconds(texts, pauses)
        assert result == pytest.approx(expected)

    def test_empty_segments_returns_zero(self) -> None:
        assert estimate_draft_duration_seconds([], []) == 0.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            estimate_draft_duration_seconds(["hello"], [0.0, 0.0])

    def test_custom_default_gap(self) -> None:
        texts = ["word"] * 2
        pauses = [0.0, 0.0]
        result = estimate_draft_duration_seconds(texts, pauses, default_gap_seconds=1.0)
        # word ≈ 60/140 s each; gap 1.0s between first and second
        expected = 2 * (60.0 / 140) + 1.0
        assert result == pytest.approx(expected)

    def test_final_segment_pause_included_no_gap(self) -> None:
        texts = ["hello"]
        pauses = [2.0]
        result = estimate_draft_duration_seconds(texts, pauses, default_gap_seconds=0.35)
        # speech + pause_after (no gap after last)
        expected = estimate_spoken_seconds("hello") + 2.0
        assert result == pytest.approx(expected)


class TestCheckDurationBudget:
    def test_within_budget_passes(self) -> None:
        assert check_duration_budget(60.0, 60.0) is True

    def test_exactly_at_tolerance_passes(self) -> None:
        # 60 * 1.30 == 78; estimated 78 should pass
        assert check_duration_budget(78.0, 60.0, tolerance=0.30) is True

    def test_over_tolerance_fails(self) -> None:
        assert check_duration_budget(78.1, 60.0, tolerance=0.30) is False

    def test_well_under_budget_passes(self) -> None:
        assert check_duration_budget(10.0, 600.0) is True

    def test_zero_budget_with_zero_estimated_passes(self) -> None:
        assert check_duration_budget(0.0, 0.0) is True

    def test_default_tolerance_matches_constant(self) -> None:
        budget = 100.0
        limit = budget * (1 + DEFAULT_DURATION_TOLERANCE)
        assert check_duration_budget(limit, budget) is True
        assert check_duration_budget(limit + 0.01, budget) is False
