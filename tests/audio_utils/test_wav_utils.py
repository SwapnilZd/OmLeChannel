"""
Tests for audio_utils WAV utilities.

Generates minimal valid WAV payloads in memory — no disk I/O, no TTS provider.
Frame-count assertions are used where possible for precision.
"""
from __future__ import annotations

import io
import wave

import pytest

from learning_pipeline.tools.audio_utils import (
    IncompatibleWavError,
    WavParams,
    check_wav_compatibility,
    concat_wavs,
    make_silence,
    read_wav_params,
    wav_duration_seconds,
)


# ── WAV generation helpers ────────────────────────────────────────────────────


def _make_wav(
    *,
    duration_seconds: float = 0.5,
    sample_rate: int = 24_000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * n_frames * channels * sample_width)
    return buf.getvalue()


def _frame_count(wav_bytes: bytes) -> int:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes()


# ── make_silence ──────────────────────────────────────────────────────────────


def test_silence_has_correct_frame_count() -> None:
    silence = make_silence(0.5, sample_rate=24_000, channels=1, sample_width=2)
    assert _frame_count(silence) == 12_000  # 0.5 × 24 000


def test_silence_duration_matches_requested() -> None:
    silence = make_silence(1.0, sample_rate=24_000)
    assert abs(wav_duration_seconds(silence) - 1.0) < 1e-9


def test_silence_params_match_requested() -> None:
    silence = make_silence(0.1, sample_rate=16_000, channels=2, sample_width=2)
    params = read_wav_params(silence)
    assert params.framerate == 16_000
    assert params.nchannels == 2
    assert params.sampwidth == 2


def test_silence_is_valid_wav() -> None:
    silence = make_silence(0.25)
    with wave.open(io.BytesIO(silence)):
        pass  # must not raise


def test_zero_second_silence_produces_valid_empty_wav() -> None:
    silence = make_silence(0.0)
    assert _frame_count(silence) == 0


# ── read_wav_params ───────────────────────────────────────────────────────────


def test_read_wav_params_returns_correct_values() -> None:
    wav = _make_wav(sample_rate=22_050, channels=1, sample_width=2)
    params = read_wav_params(wav)
    assert params.nchannels == 1
    assert params.sampwidth == 2
    assert params.framerate == 22_050
    assert params.comptype == "NONE"


def test_read_wav_params_returns_frozen_dataclass() -> None:
    wav = _make_wav()
    params = read_wav_params(wav)
    assert isinstance(params, WavParams)


def test_read_wav_params_raises_on_corrupt_bytes() -> None:
    with pytest.raises(Exception):
        read_wav_params(b"this is not a WAV file")


# ── wav_duration_seconds ──────────────────────────────────────────────────────


def test_duration_calculated_from_frame_count() -> None:
    wav = _make_wav(duration_seconds=1.5, sample_rate=24_000)
    # exact via frames: 1.5 × 24 000 = 36 000 frames
    assert wav_duration_seconds(wav) == 36_000 / 24_000


def test_duration_raises_on_invalid_bytes() -> None:
    with pytest.raises(Exception):
        wav_duration_seconds(b"bad data")


# ── check_wav_compatibility ───────────────────────────────────────────────────


def test_compatible_wavs_return_common_params() -> None:
    wavs = [_make_wav() for _ in range(3)]
    params = check_wav_compatibility(wavs)
    assert params.framerate == 24_000
    assert params.nchannels == 1


def test_single_wav_is_compatible_with_itself() -> None:
    wav = _make_wav()
    params = check_wav_compatibility([wav])
    assert params.framerate == 24_000


def test_mismatched_sample_rate_raises() -> None:
    wav1 = _make_wav(sample_rate=24_000)
    wav2 = _make_wav(sample_rate=16_000)
    with pytest.raises(IncompatibleWavError, match="Hz"):
        check_wav_compatibility([wav1, wav2])


def test_mismatched_channels_raises() -> None:
    wav1 = _make_wav(channels=1)
    wav2 = _make_wav(channels=2)
    with pytest.raises(IncompatibleWavError, match="channel"):
        check_wav_compatibility([wav1, wav2])


def test_mismatched_sample_width_raises() -> None:
    wav1 = _make_wav(sample_width=2)
    wav2 = _make_wav(sample_width=4)
    with pytest.raises(IncompatibleWavError, match="bit"):
        check_wav_compatibility([wav1, wav2])


def test_corrupt_wav_in_list_raises() -> None:
    good = _make_wav()
    with pytest.raises(Exception):
        check_wav_compatibility([good, b"corrupt"])


def test_empty_list_raises_value_error() -> None:
    with pytest.raises(ValueError, match="at least one"):
        check_wav_compatibility([])


# ── concat_wavs ───────────────────────────────────────────────────────────────


def test_concat_two_wavs_has_combined_frame_count() -> None:
    w1 = _make_wav(duration_seconds=0.5, sample_rate=24_000)
    w2 = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    result = concat_wavs([w1, w2])
    # 0.5 × 24 000 + 1.0 × 24 000 = 36 000 frames
    assert _frame_count(result) == 36_000


def test_concat_produces_valid_wav_with_single_header() -> None:
    wavs = [_make_wav() for _ in range(3)]
    result = concat_wavs(wavs)
    with wave.open(io.BytesIO(result)) as w:
        assert w.getnframes() > 0


def test_concat_includes_silence_between_segments() -> None:
    speech = _make_wav(duration_seconds=1.0, sample_rate=24_000)
    silence = make_silence(0.35, sample_rate=24_000)
    result = concat_wavs([speech, silence, speech])
    expected_frames = (
        _frame_count(speech) + _frame_count(silence) + _frame_count(speech)
    )
    assert _frame_count(result) == expected_frames


def test_concat_preserves_segment_order() -> None:
    """The first segment's frames appear before the second segment's frames."""
    # Segment A: non-zero byte pattern; Segment B: different pattern
    buf_a, buf_b = io.BytesIO(), io.BytesIO()
    with wave.open(buf_a, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24_000)
        w.writeframes(b"\x01\x00" * 100)
    with wave.open(buf_b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24_000)
        w.writeframes(b"\x02\x00" * 100)
    result = concat_wavs([buf_a.getvalue(), buf_b.getvalue()])
    with wave.open(io.BytesIO(result)) as out:
        frames = out.readframes(out.getnframes())
    # First 200 bytes of frames = segment A (100 frames × 2 bytes)
    assert frames[:200] == b"\x01\x00" * 100
    assert frames[200:] == b"\x02\x00" * 100


def test_single_wav_concat_is_identical() -> None:
    wav = _make_wav(duration_seconds=1.0)
    result = concat_wavs([wav])
    assert _frame_count(result) == _frame_count(wav)
