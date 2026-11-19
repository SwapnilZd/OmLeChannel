"""
RealSpeechExecutor — production speech.synthesize implementation.

Responsibilities (in order):
1. Validate task inputs with SpeechSynthesisInput.
2. Resolve the provider voice from the speaker role or explicit voice_hint.
3. Call the injected SpeechClient (non-blocking via to_thread).
4. Verify the response is a readable WAV file.
5. Measure actual playback duration.
6. Estimate usage and calculate cost.
7. Persist the WAV through ArtifactStore.
8. Validate and return SpeechSynthesisOutput as a dict.

Not responsible for: concatenation, silence insertion, podcast-wide assembly,
replanning, direct DB writes, or calling other executors.
"""
from __future__ import annotations

from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactStore, ArtifactWriteError
from learning_pipeline.tools.audio_utils import (
    CHARS_PER_TOKEN,
    estimate_output_tokens,
    wav_duration_seconds,
)
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError
from learning_pipeline.tools.speech.client import SpeechClient
from learning_pipeline.tools.speech.contracts import (
    SpeechSynthesisInput,
    SpeechSynthesisOutput,
    SpeechUsage,
)


class SpeechConfigurationError(RuntimeError):
    """Voice mapping or executor configuration is incomplete."""


class SpeechProviderError(RuntimeError):
    """The upstream TTS provider returned an error or an unexpected response."""


class InvalidAudioResponseError(ValueError):
    """The TTS provider returned bytes that cannot be parsed as a valid WAV."""


class RealSpeechExecutor:
    """Production executor for ``speech.synthesize`` using an injected SpeechClient."""

    def __init__(
        self,
        *,
        client: SpeechClient,
        artifact_store: ArtifactStore,
        voice_map: dict[str, str],
        model: str,
        input_cost_per_token: float,
        output_cost_per_token: float,
        response_format: str = "wav",
    ) -> None:
        self._client = client
        self._store = artifact_store
        self._voice_map = voice_map
        self._model = model
        self._input_cost = input_cost_per_token
        self._output_cost = output_cost_per_token
        self._response_format = response_format

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # 1. Validate input contract
        try:
            inp = SpeechSynthesisInput.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid speech.synthesize input: {exc}"
            ) from exc

        # 2. Resolve voice (explicit hint takes precedence over speaker mapping)
        voice = inp.voice_hint or self._voice_map.get(inp.speaker)
        if not voice:
            raise SpeechConfigurationError(
                f"[{context.task_id}] No voice configured for speaker {inp.speaker!r}. "
                f"Available speakers: {sorted(self._voice_map)}"
            )

        # 3. Call provider (non-blocking)
        try:
            wav_bytes = await self._client.synthesize(
                text=inp.text,
                voice=voice,
                model=self._model,
                response_format=self._response_format,
            )
        except Exception as exc:
            raise SpeechProviderError(
                f"[{context.task_id}] TTS provider error: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        # 4. Validate WAV
        try:
            duration = wav_duration_seconds(wav_bytes)
        except Exception as exc:
            raise InvalidAudioResponseError(
                f"[{context.task_id}] Provider returned invalid WAV bytes: {exc}"
            ) from exc

        # 5–6. Calculate usage and cost
        chars = len(inp.text)
        input_tokens = chars / CHARS_PER_TOKEN
        output_tokens = estimate_output_tokens(wav_bytes)
        input_cost = input_tokens * self._input_cost
        output_cost = output_tokens * self._output_cost
        usage = SpeechUsage(
            input_characters=chars,
            input_tokens_estimate=round(input_tokens, 1),
            audio_duration_seconds=round(duration, 2),
            input_cost_usd=round(input_cost, 6),
            output_cost_usd=round(output_cost, 6),
            total_cost_usd=round(input_cost + output_cost, 6),
        )

        # 7. Persist artifact
        try:
            ref = await self._store.put_bytes(
                namespace=f"speech/{context.workflow_id}",
                name=f"{context.task_id}.wav",
                data=wav_bytes,
                media_type="audio/wav",
            )
        except ArtifactWriteError as exc:
            raise ArtifactWriteError(
                f"[{context.task_id}] Failed to persist audio artifact: {exc}"
            ) from exc

        # 8. Build and return validated output
        try:
            output = SpeechSynthesisOutput(
                audio_uri=ref.uri,
                media_type="audio/wav",
                duration_seconds=round(duration, 3),
                speaker=inp.speaker,
                voice=voice,
                usage=usage,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{context.task_id}] SpeechSynthesisOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()
