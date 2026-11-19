"""
Tests for AudioAssemblyInput, AudioAssemblyOutput, and PodcastUsageSummary contracts.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.tools.audio_assembly.contracts import (
    AudioAssemblyInput,
    AudioAssemblyOutput,
    AudioAssemblySegment,
    PodcastUsageSummary,
)


# ── AudioAssemblySegment ──────────────────────────────────────────────────────


def test_valid_segment_parses() -> None:
    seg = AudioAssemblySegment(
        segment_id="seg-1",
        audio_uri="artifact://speech/wf-1/seg-1.wav",
    )
    assert seg.segment_id == "seg-1"
    assert seg.pause_after_seconds == 0.0
    assert seg.usage is None
    assert seg.speaker is None


def test_blank_segment_id_fails() -> None:
    with pytest.raises(ValidationError, match="blank"):
        AudioAssemblySegment(segment_id="  ", audio_uri="artifact://x/y.wav")


def test_blank_audio_uri_fails() -> None:
    with pytest.raises(ValidationError, match="blank"):
        AudioAssemblySegment(segment_id="s1", audio_uri="")


def test_negative_pause_fails() -> None:
    with pytest.raises(ValidationError):
        AudioAssemblySegment(segment_id="s1", audio_uri="fake://x.wav", pause_after_seconds=-0.1)


def test_zero_pause_is_valid() -> None:
    seg = AudioAssemblySegment(segment_id="s1", audio_uri="fake://x.wav", pause_after_seconds=0.0)
    assert seg.pause_after_seconds == 0.0


# ── AudioAssemblyInput ────────────────────────────────────────────────────────


def _seg(n: int, **kwargs) -> AudioAssemblySegment:
    return AudioAssemblySegment(segment_id=f"seg-{n}", audio_uri=f"fake://seg-{n}.wav", **kwargs)


def test_valid_input_parses() -> None:
    inp = AudioAssemblyInput(
        deliverable_id="podcast-01",
        segments=(_seg(1), _seg(2)),
    )
    assert inp.deliverable_id == "podcast-01"
    assert len(inp.segments) == 2
    assert inp.default_gap_seconds == 0.35


def test_empty_segments_fails() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        AudioAssemblyInput(deliverable_id="p", segments=())


def test_duplicate_segment_ids_fail() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        AudioAssemblyInput(
            deliverable_id="p",
            segments=(
                AudioAssemblySegment(segment_id="s1", audio_uri="fake://a.wav"),
                AudioAssemblySegment(segment_id="s1", audio_uri="fake://b.wav"),
            ),
        )


def test_blank_deliverable_id_fails() -> None:
    with pytest.raises(ValidationError, match="blank"):
        AudioAssemblyInput(deliverable_id="", segments=(_seg(1),))


def test_negative_default_gap_fails() -> None:
    with pytest.raises(ValidationError):
        AudioAssemblyInput(deliverable_id="p", segments=(_seg(1),), default_gap_seconds=-1.0)


def test_unsafe_output_filename_fails() -> None:
    with pytest.raises(ValidationError, match="path"):
        AudioAssemblyInput(
            deliverable_id="p", segments=(_seg(1),), output_filename="../etc/passwd"
        )


def test_safe_output_filename_is_valid() -> None:
    inp = AudioAssemblyInput(
        deliverable_id="p", segments=(_seg(1),), output_filename="final-podcast.wav"
    )
    assert inp.output_filename == "final-podcast.wav"


def test_output_filename_none_is_valid() -> None:
    inp = AudioAssemblyInput(deliverable_id="p", segments=(_seg(1),))
    assert inp.output_filename is None


def test_input_is_frozen() -> None:
    inp = AudioAssemblyInput(deliverable_id="p", segments=(_seg(1),))
    with pytest.raises(ValidationError):
        inp.deliverable_id = "changed"  # type: ignore[misc]


# ── AudioAssemblyOutput ───────────────────────────────────────────────────────


def _zero_usage() -> PodcastUsageSummary:
    return PodcastUsageSummary(
        total_input_characters=0,
        total_input_tokens_estimate=0.0,
        total_audio_duration_seconds=0.0,
        total_pause_duration_seconds=0.0,
        total_input_cost_usd=0.0,
        total_output_cost_usd=0.0,
        total_cost_usd=0.0,
    )


def test_valid_output_parses() -> None:
    output = AudioAssemblyOutput(
        deliverable_id="podcast-01",
        audio_uri="artifact://deliverables/wf/podcast.wav",
        costs_uri="artifact://deliverables/wf/podcast.costs.json",
        duration_seconds=45.3,
        segment_count=2,
        usage=_zero_usage(),
    )
    assert output.media_type == "audio/wav"
    assert output.segment_count == 2


def test_fake_uris_are_valid_output() -> None:
    output = AudioAssemblyOutput(
        deliverable_id="p",
        audio_uri="fake://deliverables/wf/p.wav",
        costs_uri="fake://deliverables/wf/p.costs.json",
        duration_seconds=2.0,
        segment_count=2,
        usage=_zero_usage(),
    )
    assert output.audio_uri.startswith("fake://")


def test_output_model_dump_is_json_serializable() -> None:
    import json

    output = AudioAssemblyOutput(
        deliverable_id="p",
        audio_uri="fake://x.wav",
        costs_uri="fake://x.json",
        duration_seconds=1.0,
        segment_count=1,
        usage=_zero_usage(),
    )
    json.dumps(output.model_dump())  # must not raise


def test_output_is_frozen() -> None:
    output = AudioAssemblyOutput(
        deliverable_id="p",
        audio_uri="fake://x.wav",
        costs_uri="fake://x.json",
        duration_seconds=1.0,
        segment_count=1,
        usage=_zero_usage(),
    )
    with pytest.raises(ValidationError):
        output.audio_uri = "changed"  # type: ignore[misc]


# ── PodcastUsageSummary ───────────────────────────────────────────────────────


def test_usage_summary_parses() -> None:
    usage = PodcastUsageSummary(
        total_input_characters=120,
        total_input_tokens_estimate=30.0,
        total_audio_duration_seconds=4.5,
        total_pause_duration_seconds=0.7,
        total_input_cost_usd=0.00003,
        total_output_cost_usd=0.0009,
        total_cost_usd=0.00093,
    )
    assert usage.total_input_characters == 120
    assert usage.total_cost_usd == 0.00093
