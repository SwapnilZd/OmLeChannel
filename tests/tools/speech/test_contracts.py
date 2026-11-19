"""
Tests for SpeechSynthesisInput, SpeechSynthesisOutput, and SpeechUsage contracts.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from learning_pipeline.tools.speech.contracts import (
    SpeechSynthesisInput,
    SpeechSynthesisOutput,
    SpeechUsage,
)


# ── SpeechSynthesisInput ──────────────────────────────────────────────────────


def test_valid_input_parses() -> None:
    inp = SpeechSynthesisInput(
        text="Hello world",
        speaker="Host",
        line_id="line-01",
    )
    assert inp.text == "Hello world"
    assert inp.speaker == "Host"
    assert inp.line_id == "line-01"
    assert inp.voice_hint is None
    assert inp.pause_after_seconds == 0.0


def test_input_with_optional_fields() -> None:
    inp = SpeechSynthesisInput(
        text="Hello",
        speaker="Expert",
        line_id="l-02",
        voice_hint="Charon",
        pause_after_seconds=0.5,
    )
    assert inp.voice_hint == "Charon"
    assert inp.pause_after_seconds == 0.5


def test_blank_text_fails() -> None:
    with pytest.raises(ValidationError, match="blank"):
        SpeechSynthesisInput(text="   ", speaker="Host", line_id="l-01")


def test_empty_text_fails() -> None:
    with pytest.raises(ValidationError):
        SpeechSynthesisInput(text="", speaker="Host", line_id="l-01")


def test_blank_speaker_fails() -> None:
    with pytest.raises(ValidationError, match="blank"):
        SpeechSynthesisInput(text="Hello", speaker="  ", line_id="l-01")


def test_blank_line_id_fails() -> None:
    with pytest.raises(ValidationError, match="blank"):
        SpeechSynthesisInput(text="Hello", speaker="Host", line_id="")


def test_negative_pause_fails() -> None:
    with pytest.raises(ValidationError):
        SpeechSynthesisInput(
            text="Hello",
            speaker="Host",
            line_id="l-01",
            pause_after_seconds=-0.1,
        )


def test_zero_pause_is_valid() -> None:
    inp = SpeechSynthesisInput(text="Hi", speaker="Host", line_id="l-01", pause_after_seconds=0.0)
    assert inp.pause_after_seconds == 0.0


def test_input_is_frozen() -> None:
    inp = SpeechSynthesisInput(text="Hi", speaker="Host", line_id="l-01")
    with pytest.raises(ValidationError):
        inp.text = "changed"  # type: ignore[misc]


# ── SpeechSynthesisOutput ─────────────────────────────────────────────────────


def _valid_usage() -> SpeechUsage:
    return SpeechUsage(
        input_characters=11,
        input_tokens_estimate=2.75,
        audio_duration_seconds=0.8,
        input_cost_usd=0.0,
        output_cost_usd=0.0,
        total_cost_usd=0.0,
    )


def test_valid_output_parses() -> None:
    output = SpeechSynthesisOutput(
        audio_uri="artifact://speech/wf-1/seg.wav",
        media_type="audio/wav",
        duration_seconds=1.2,
        speaker="Host",
        voice="Aoede",
        usage=_valid_usage(),
    )
    assert output.audio_uri == "artifact://speech/wf-1/seg.wav"
    assert output.media_type == "audio/wav"


def test_fake_uri_is_valid_output() -> None:
    output = SpeechSynthesisOutput(
        audio_uri="fake://audio/task-1.wav",
        duration_seconds=1.0,
        speaker="Host",
        voice="fake-voice",
        usage=_valid_usage(),
    )
    assert output.audio_uri.startswith("fake://")


def test_invalid_media_type_fails() -> None:
    with pytest.raises(ValidationError):
        SpeechSynthesisOutput(
            audio_uri="artifact://x/y.wav",
            media_type="audio/mp3",  # not allowed
            duration_seconds=1.0,
            speaker="Host",
            voice="Aoede",
            usage=_valid_usage(),
        )


def test_output_is_frozen() -> None:
    output = SpeechSynthesisOutput(
        audio_uri="artifact://x/y.wav",
        duration_seconds=1.0,
        speaker="Host",
        voice="Aoede",
        usage=_valid_usage(),
    )
    with pytest.raises(ValidationError):
        output.audio_uri = "changed"  # type: ignore[misc]


def test_output_model_dump_is_json_serializable() -> None:
    import json

    output = SpeechSynthesisOutput(
        audio_uri="fake://audio/task-1.wav",
        duration_seconds=1.0,
        speaker="Host",
        voice="fake-voice",
        usage=_valid_usage(),
    )
    dumped = output.model_dump()
    json.dumps(dumped)  # must not raise


# ── SpeechUsage ───────────────────────────────────────────────────────────────


def test_usage_parses() -> None:
    usage = _valid_usage()
    assert usage.input_characters == 11
    assert usage.total_cost_usd == 0.0
