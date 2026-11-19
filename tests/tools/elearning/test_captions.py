"""Tests for _captions.py — SRT→VTT conversion and validation."""
from __future__ import annotations

import pytest

from learning_pipeline.tools.elearning_bundle._captions import (
    CaptionConversionError,
    convert_srt_to_vtt,
    ensure_vtt,
    validate_vtt,
)

_SRT_SAMPLE = b"""\
1
00:00:00,000 --> 00:00:02,000
Hello world.

2
00:00:02,500 --> 00:00:05,000
This is a subtitle.
"""

_VTT_SAMPLE = b"""\
WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world.

00:00:02.500 --> 00:00:05.000
This is a subtitle.
"""


# ── convert_srt_to_vtt ────────────────────────────────────────────────────────


def test_srt_to_vtt_produces_webvtt_header():
    result = convert_srt_to_vtt(_SRT_SAMPLE)
    assert result.startswith(b"WEBVTT")


def test_srt_to_vtt_replaces_comma_separator():
    result = convert_srt_to_vtt(_SRT_SAMPLE).decode("utf-8")
    assert "00:00:00.000 --> 00:00:02.000" in result
    assert "," not in result.split("-->")[0].split("\n")[-1]


def test_srt_to_vtt_removes_cue_numbers():
    result = convert_srt_to_vtt(_SRT_SAMPLE).decode("utf-8")
    lines = [l.strip() for l in result.splitlines()]
    assert "1" not in lines
    assert "2" not in lines


def test_srt_to_vtt_empty_raises():
    with pytest.raises(CaptionConversionError, match="empty"):
        convert_srt_to_vtt(b"   ")


def test_srt_to_vtt_no_timestamp_raises():
    with pytest.raises(CaptionConversionError, match="SRT timestamp"):
        convert_srt_to_vtt(b"Not an SRT file at all.\n")


def test_srt_to_vtt_non_utf8_raises():
    with pytest.raises(CaptionConversionError, match="UTF-8"):
        convert_srt_to_vtt(b"\xff\xfe invalid bytes")


# ── validate_vtt ──────────────────────────────────────────────────────────────


def test_validate_vtt_passes_valid_file():
    validate_vtt(_VTT_SAMPLE)


def test_validate_vtt_empty_raises():
    with pytest.raises(CaptionConversionError, match="empty"):
        validate_vtt(b"")


def test_validate_vtt_missing_header_raises():
    with pytest.raises(CaptionConversionError, match="WEBVTT"):
        validate_vtt(b"Not a VTT file\n00:00:00.000 --> 00:00:01.000\nText\n")


def test_validate_vtt_no_timing_cues_raises():
    with pytest.raises(CaptionConversionError, match="timing cues"):
        validate_vtt(b"WEBVTT\n\nNo actual cues here.\n")


# ── ensure_vtt ────────────────────────────────────────────────────────────────


def test_ensure_vtt_with_vtt_media_type_passes_through():
    result = ensure_vtt(_VTT_SAMPLE, "text/vtt")
    assert result == _VTT_SAMPLE


def test_ensure_vtt_with_srt_media_type_converts():
    result = ensure_vtt(_SRT_SAMPLE, "text/srt")
    assert result.startswith(b"WEBVTT")


def test_ensure_vtt_unsupported_type_raises():
    with pytest.raises(CaptionConversionError, match="Unsupported caption"):
        ensure_vtt(b"data", "application/octet-stream")


def test_ensure_vtt_srt_validates_after_conversion():
    result = ensure_vtt(_SRT_SAMPLE, "text/srt")
    validate_vtt(result)


def test_ensure_vtt_case_insensitive_media_type():
    result = ensure_vtt(_VTT_SAMPLE, "TEXT/VTT")
    assert result == _VTT_SAMPLE
