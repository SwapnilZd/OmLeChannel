from __future__ import annotations

import pytest

from learning_pipeline.media_validation import (
    MP4DimensionError,
    read_mp4_dimensions,
    validate_mp4_dimensions,
)


def _box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def _minimal_mp4(width: int, height: int) -> bytes:
    ftyp = _box(b"ftyp", b"mp42")
    tkhd = _box(
        b"tkhd",
        b"\x00" * 16 + (width << 16).to_bytes(4, "big") + (height << 16).to_bytes(4, "big"),
    )
    return ftyp + _box(b"moov", _box(b"trak", tkhd))


def test_reads_dimensions_from_video_track_header():
    assert read_mp4_dimensions(_minimal_mp4(1280, 720)) == (1280, 720)


def test_accepts_matching_dimensions():
    validate_mp4_dimensions(
        _minimal_mp4(1280, 720), expected_width=1280, expected_height=720
    )


def test_rejects_mismatched_dimensions():
    with pytest.raises(MP4DimensionError, match="1920x1080.*1280x720"):
        validate_mp4_dimensions(
            _minimal_mp4(1920, 1080), expected_width=1280, expected_height=720
        )


def test_rejects_header_only_placeholder():
    with pytest.raises(MP4DimensionError, match="no video track dimensions"):
        read_mp4_dimensions(_box(b"ftyp", b"mp42"))
