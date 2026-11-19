"""
Pure audio utility functions shared by the speech and assembly executors.

No I/O, no network access, no external dependencies beyond the Python standard
library.  Extracted from the feasibility podcast_renderer for reuse across
executor implementations.

Phase 7 exports: wav_duration_seconds, estimate_output_tokens, CHARS_PER_TOKEN
Phase 8 exports: WavParams, read_wav_params, check_wav_compatibility, make_silence, concat_wavs
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass

CHARS_PER_TOKEN: int = 4
"""Character-to-token ratio for TTS cost estimation (4 chars ≈ 1 token)."""


# ── WAV parameter types ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class WavParams:
    """PCM WAV format parameters extracted from a WAV header."""

    nchannels: int
    sampwidth: int
    framerate: int
    comptype: str


class IncompatibleWavError(ValueError):
    """Raised when WAV segments have incompatible audio parameters."""


# ── WAV introspection ─────────────────────────────────────────────────────────


def read_wav_params(wav_bytes: bytes) -> WavParams:
    """Read format parameters from a WAV payload without decoding frames.

    Raises ``wave.Error`` if ``wav_bytes`` is not a valid WAV file.
    """
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return WavParams(
            nchannels=w.getnchannels(),
            sampwidth=w.getsampwidth(),
            framerate=w.getframerate(),
            comptype=w.getcomptype(),
        )


def wav_duration_seconds(wav_bytes: bytes) -> float:
    """Return the playback duration of a WAV payload in seconds.

    Raises ``wave.Error`` if the bytes are not a valid WAV file.
    """
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / w.getframerate()


def estimate_output_tokens(wav_bytes: bytes) -> float:
    """Estimate output tokens from audio byte length.

    Assumes 24 kHz 16-bit mono (48 000 bytes/s).  Used for cost calculations.
    """
    return (len(wav_bytes) / 48_000) * 1_000 / CHARS_PER_TOKEN


# ── Compatibility validation ──────────────────────────────────────────────────


def check_wav_compatibility(wavs: list[bytes]) -> WavParams:
    """Validate that all WAVs share the same PCM format.

    Returns the common ``WavParams``.  Raises ``IncompatibleWavError`` if any
    segment differs or uses a compressed format.

    Call this on the speech-segment WAVs *before* generating silence or
    concatenating, so all problems are reported before writing any output.
    """
    if not wavs:
        raise ValueError("check_wav_compatibility requires at least one WAV segment")

    params_list = [read_wav_params(w) for w in wavs]
    ref = params_list[0]

    if ref.comptype != "NONE":
        raise IncompatibleWavError(
            f"WAV compression {ref.comptype!r} is not supported — only PCM (NONE) is accepted"
        )

    for i, p in enumerate(params_list[1:], start=1):
        if p.comptype != "NONE":
            raise IncompatibleWavError(
                f"Segment {i}: WAV compression {p.comptype!r} is not supported"
            )
        if p.nchannels != ref.nchannels:
            raise IncompatibleWavError(
                f"Segment {i}: {p.nchannels} channels vs segment 0: {ref.nchannels} channels"
            )
        if p.sampwidth != ref.sampwidth:
            raise IncompatibleWavError(
                f"Segment {i}: {p.sampwidth*8}-bit vs segment 0: {ref.sampwidth*8}-bit"
            )
        if p.framerate != ref.framerate:
            raise IncompatibleWavError(
                f"Segment {i}: {p.framerate} Hz vs segment 0: {ref.framerate} Hz"
            )

    return ref


# ── Audio generation ──────────────────────────────────────────────────────────


def make_silence(
    seconds: float,
    *,
    sample_rate: int = 24_000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Generate WAV-encoded silence of the requested duration.

    Uses the same parameters as the surrounding speech WAVs so the silence
    segments are format-compatible for concatenation.
    """
    buf = io.BytesIO()
    n_frames = int(sample_rate * seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * n_frames * channels * sample_width)
    return buf.getvalue()


def concat_wavs(segments: list[bytes]) -> bytes:
    """Concatenate WAV segments into one WAV payload.

    All segments must share the same PCM format parameters (sample rate,
    channels, sample width).  Reads audio frames rather than raw bytes so the
    output has one valid WAV header and no embedded sub-headers.
    """
    buf = io.BytesIO()
    params_set = False
    with wave.open(buf, "wb") as out:
        for seg in segments:
            with wave.open(io.BytesIO(seg)) as w:
                if not params_set:
                    out.setparams(w.getparams())
                    params_set = True
                out.writeframes(w.readframes(w.getnframes()))
    return buf.getvalue()
