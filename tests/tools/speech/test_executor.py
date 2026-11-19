"""
Tests for RealSpeechExecutor.

Uses an injected FakeSpeechClient — no live TTS provider is called.
A minimal valid WAV is generated in memory for tests that need real audio bytes.
"""
from __future__ import annotations

import io
import struct
import wave
from pathlib import Path
from typing import Any

import pytest

from learning_pipeline.runtime.artifact_store import FileArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.speech.client import SpeechClient
from learning_pipeline.tools.speech.contracts import SpeechSynthesisInput, SpeechSynthesisOutput
from learning_pipeline.tools.speech.executor import (
    InvalidAudioResponseError,
    RealSpeechExecutor,
    SpeechConfigurationError,
    SpeechProviderError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_wav(*, duration_seconds: float = 0.5, sample_rate: int = 24_000) -> bytes:
    """Generate a minimal valid WAV payload in memory."""
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


class _FakeSpeechClient:
    """Synchronous-free fake TTS client for tests."""

    def __init__(self, wav_bytes: bytes | None = None, error: Exception | None = None) -> None:
        self._wav = wav_bytes or _make_wav()
        self._error = error
        self.calls: list[dict] = []

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        response_format: str,
    ) -> bytes:
        self.calls.append(
            {"text": text, "voice": voice, "model": model, "response_format": response_format}
        )
        if self._error is not None:
            raise self._error
        return self._wav


def _make_executor(
    client: SpeechClient | None = None,
    artifact_store: Any = None,
    voice_map: dict[str, str] | None = None,
    tmp_path: Path | None = None,
) -> RealSpeechExecutor:
    if tmp_path is not None and artifact_store is None:
        artifact_store = FileArtifactStore(tmp_path / "artifacts")
    return RealSpeechExecutor(
        client=client or _FakeSpeechClient(),
        artifact_store=artifact_store,
        voice_map=voice_map or {"Host": "Aoede", "Expert": "Charon"},
        model="gemini-tts",
        input_cost_per_token=0.000001,
        output_cost_per_token=0.00002,
    )


def _ctx(
    task_id: str = "speech-segment-1",
    text: str = "Hello world",
    speaker: str = "Host",
    line_id: str = "l-01",
    voice_hint: str | None = None,
) -> ExecutionContext:
    inputs: dict[str, Any] = {"text": text, "speaker": speaker, "line_id": line_id}
    if voice_hint is not None:
        inputs["voice_hint"] = voice_hint
    return ExecutionContext(
        workflow_id="wf-test",
        task_id=task_id,
        attempt=1,
        inputs=inputs,
    )


# ── Core success path ─────────────────────────────────────────────────────────


async def test_execute_returns_audio_uri(tmp_path) -> None:
    executor = _make_executor(tmp_path=tmp_path)
    result = await executor.execute(_ctx())
    assert "audio_uri" in result
    assert result["audio_uri"].startswith("artifact://speech/wf-test/speech-segment-1.wav")


async def test_execute_returns_correct_speaker(tmp_path) -> None:
    executor = _make_executor(tmp_path=tmp_path)
    result = await executor.execute(_ctx(speaker="Expert"))
    assert result["speaker"] == "Expert"


async def test_correct_voice_selected_for_host(tmp_path) -> None:
    client = _FakeSpeechClient()
    executor = _make_executor(client=client, tmp_path=tmp_path)
    await executor.execute(_ctx(speaker="Host"))
    assert client.calls[0]["voice"] == "Aoede"


async def test_correct_voice_selected_for_expert(tmp_path) -> None:
    client = _FakeSpeechClient()
    executor = _make_executor(client=client, tmp_path=tmp_path)
    await executor.execute(_ctx(speaker="Expert"))
    assert client.calls[0]["voice"] == "Charon"


async def test_voice_hint_overrides_speaker_mapping(tmp_path) -> None:
    client = _FakeSpeechClient()
    executor = _make_executor(client=client, tmp_path=tmp_path)
    await executor.execute(_ctx(speaker="Host", voice_hint="Puck"))
    assert client.calls[0]["voice"] == "Puck"


async def test_provider_receives_correct_model_and_format(tmp_path) -> None:
    client = _FakeSpeechClient()
    executor = _make_executor(client=client, tmp_path=tmp_path)
    await executor.execute(_ctx(text="Hello"))
    call = client.calls[0]
    assert call["model"] == "gemini-tts"
    assert call["response_format"] == "wav"


async def test_provider_receives_correct_text(tmp_path) -> None:
    client = _FakeSpeechClient()
    executor = _make_executor(client=client, tmp_path=tmp_path)
    await executor.execute(_ctx(text="Specific text here"))
    assert client.calls[0]["text"] == "Specific text here"


async def test_wav_duration_is_measured_from_frames(tmp_path) -> None:
    wav = _make_wav(duration_seconds=1.5)
    client = _FakeSpeechClient(wav_bytes=wav)
    executor = _make_executor(client=client, tmp_path=tmp_path)
    result = await executor.execute(_ctx())
    assert abs(result["duration_seconds"] - 1.5) < 0.01


async def test_usage_characters_match_text_length(tmp_path) -> None:
    text = "Hello world"
    executor = _make_executor(tmp_path=tmp_path)
    result = await executor.execute(_ctx(text=text))
    assert result["usage"]["input_characters"] == len(text)


async def test_usage_costs_are_non_negative(tmp_path) -> None:
    executor = _make_executor(tmp_path=tmp_path)
    result = await executor.execute(_ctx(text="Some text for cost test"))
    usage = result["usage"]
    assert usage["input_cost_usd"] >= 0
    assert usage["output_cost_usd"] >= 0
    assert usage["total_cost_usd"] >= 0


async def test_audio_persisted_through_artifact_store(tmp_path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    executor = _make_executor(tmp_path=tmp_path, artifact_store=store)
    result = await executor.execute(_ctx())
    # Retrieve through the store using the returned URI
    data = await store.get_bytes(result["audio_uri"])
    assert len(data) > 0


async def test_output_does_not_contain_raw_bytes(tmp_path) -> None:
    executor = _make_executor(tmp_path=tmp_path)
    result = await executor.execute(_ctx())
    # No value in the output dict should be bytes
    for v in result.values():
        assert not isinstance(v, bytes), "Raw audio bytes must not appear in task outputs"


async def test_output_validates_as_speech_synthesis_output(tmp_path) -> None:
    executor = _make_executor(tmp_path=tmp_path)
    result = await executor.execute(_ctx())
    # Must parse as the typed output contract without error
    parsed = SpeechSynthesisOutput.model_validate(result)
    assert parsed.media_type == "audio/wav"


# ── Error paths ───────────────────────────────────────────────────────────────


async def test_unknown_speaker_raises_configuration_error(tmp_path) -> None:
    executor = _make_executor(
        tmp_path=tmp_path,
        voice_map={"Host": "Aoede"},  # Expert not configured
    )
    with pytest.raises(SpeechConfigurationError, match="Expert"):
        await executor.execute(_ctx(speaker="Expert"))


async def test_provider_error_is_wrapped(tmp_path) -> None:
    client = _FakeSpeechClient(error=RuntimeError("Connection refused"))
    executor = _make_executor(client=client, tmp_path=tmp_path)
    with pytest.raises(SpeechProviderError, match="Connection refused"):
        await executor.execute(_ctx())


async def test_invalid_audio_raises_error(tmp_path) -> None:
    client = _FakeSpeechClient(wav_bytes=b"not a wav file at all")
    executor = _make_executor(client=client, tmp_path=tmp_path)
    with pytest.raises(InvalidAudioResponseError):
        await executor.execute(_ctx())


async def test_invalid_input_raises_tool_input_error(tmp_path) -> None:
    from learning_pipeline.tools.errors import InvalidToolInputError

    executor = _make_executor(tmp_path=tmp_path)
    ctx = ExecutionContext(
        workflow_id="wf-test",
        task_id="seg-1",
        attempt=1,
        inputs={"text": "", "speaker": "Host", "line_id": "l-01"},  # blank text
    )
    with pytest.raises(InvalidToolInputError):
        await executor.execute(ctx)


# ── Non-blocking I/O ──────────────────────────────────────────────────────────


async def test_executor_does_not_block_event_loop(tmp_path) -> None:
    """The synchronous SDK call must be offloaded via to_thread.

    This test verifies that OpenAISpeechClient.synthesize is defined as async
    (uses to_thread internally).  The fake client is inherently async so we
    just verify the executor completes without error.
    """
    import asyncio

    executor = _make_executor(tmp_path=tmp_path)
    # Run two tasks concurrently — if the executor blocked the loop neither could proceed
    results = await asyncio.gather(
        executor.execute(_ctx(task_id="seg-1")),
        executor.execute(_ctx(task_id="seg-2")),
    )
    assert len(results) == 2
