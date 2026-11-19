"""Deterministic caption format utilities.

The video_player.html.j2 template uses a <track> element with kind="captions".
Browsers expect WebVTT (.vtt).  HeyGen may return SRT subtitles.  This module
converts SRT to WebVTT and validates both formats before they are staged.

SRT format:
    1
    00:00:00,000 --> 00:00:02,000
    Cue text.

WebVTT format:
    WEBVTT

    00:00:00.000 --> 00:00:02.000
    Cue text.

Differences:
- WebVTT requires a "WEBVTT" header line.
- WebVTT uses "." as the millisecond separator; SRT uses ",".
- Cue index numbers are optional in WebVTT.
"""
from __future__ import annotations

import re

_SRT_TIMESTAMP_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}),(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}),(\d{3})"
)
_VTT_HEADER = "WEBVTT"
_VTT_TIMING_RE = re.compile(
    r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}"
)


class CaptionConversionError(ValueError):
    """Raised when caption bytes cannot be parsed or converted."""


def convert_srt_to_vtt(data: bytes) -> bytes:
    """Convert SRT subtitle bytes to WebVTT bytes.

    Raises CaptionConversionError when the input is not valid SRT or is empty.
    """
    try:
        text = data.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise CaptionConversionError(f"Caption bytes are not valid UTF-8: {exc}") from exc

    if not text:
        raise CaptionConversionError("Caption content is empty")

    if not _SRT_TIMESTAMP_RE.search(text):
        raise CaptionConversionError(
            "No SRT timestamp found — input does not appear to be SRT format"
        )

    converted = _SRT_TIMESTAMP_RE.sub(
        lambda m: f"{m.group(1)}.{m.group(2)} --> {m.group(3)}.{m.group(4)}",
        text,
    )

    lines = converted.splitlines()
    # Drop numeric-only cue-index lines (optional in VTT).
    # A line is a cue index when it contains only digits and the *next* non-empty
    # line is a VTT timing line (i.e. it's the sequence number at the start of a block).
    cleaned: list[str] = []
    for i, line in enumerate(lines):
        if line.strip().isdigit():
            # Look ahead for the next non-empty line
            next_content = next(
                (l for l in lines[i + 1:] if l.strip()), ""
            )
            if _VTT_TIMING_RE.match(next_content.strip()):
                continue  # skip cue index number
        cleaned.append(line)

    vtt = f"{_VTT_HEADER}\n\n" + "\n".join(cleaned).lstrip()
    return vtt.encode("utf-8")


def validate_vtt(data: bytes) -> None:
    """Raise CaptionConversionError if data is not a non-empty WebVTT file."""
    try:
        text = data.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise CaptionConversionError(f"Caption bytes are not valid UTF-8: {exc}") from exc

    if not text:
        raise CaptionConversionError("WebVTT content is empty")

    if not text.startswith(_VTT_HEADER):
        raise CaptionConversionError(
            f"WebVTT file must start with 'WEBVTT'; got {text[:20]!r}"
        )

    if not _VTT_TIMING_RE.search(text):
        raise CaptionConversionError("WebVTT file contains no timing cues")


def ensure_vtt(data: bytes, source_media_type: str) -> bytes:
    """Return VTT bytes, converting from SRT if necessary.

    Raises CaptionConversionError when:
    - The source media type is neither VTT nor SRT.
    - Conversion fails.
    - VTT validation fails.
    """
    mt = source_media_type.strip().lower()
    if mt == "text/vtt":
        validate_vtt(data)
        return data
    if mt == "text/srt":
        vtt_bytes = convert_srt_to_vtt(data)
        validate_vtt(vtt_bytes)
        return vtt_bytes
    raise CaptionConversionError(
        f"Unsupported caption media type {source_media_type!r}; "
        "expected 'text/vtt' or 'text/srt'"
    )
