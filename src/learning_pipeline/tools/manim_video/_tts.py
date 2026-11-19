"""Manim narration synthesis service.

Wraps OpenAISpeechClient (from tools/speech/client.py) for use by the
Manim controller. Does NOT use RealSpeechExecutor — that executor is
oriented around per-segment podcast assembly with its own artifact store.

The narration service:
- Receives the complete narration script from AnimationBrief.
- Calls the provider once for the full script.
- Returns raw WAV bytes for checkpoint persistence.
- Does not write to ArtifactStore directly (the controller owns persistence).

Voice profiles are resolved to provider-specific voice names via a registry.
Unknown profiles fall back to the default voice.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from llm_gateway import ModelAlias

# Default voice profile → provider voice name mapping.
_VOICE_REGISTRY: dict[str, str] = {
    "default": "nova",
    "instructor": "onyx",
    "friendly": "alloy",
    "authoritative": "echo",
    "warm": "shimmer",
    "nova": "nova",
    "onyx": "onyx",
    "alloy": "alloy",
    "echo": "echo",
    "shimmer": "shimmer",
}

_DEFAULT_VOICE = "nova"
_DEFAULT_MODEL = ModelAlias.MANIM_SPEECH_SYNTHESIS
_DEFAULT_FORMAT = "wav"


@runtime_checkable
class ManimNarrationService(Protocol):
    """Provider-neutral interface for Manim narration synthesis."""

    async def synthesize(
        self,
        *,
        text: str,
        voice_profile: str | None,
    ) -> bytes: ...


class FakeManimNarrationService:
    """Returns deterministic fake WAV bytes without calling any provider."""

    # Minimal valid WAV header (44 bytes) + 1 second of silence at 24kHz/16bit/mono.
    _FAKE_WAV = (
        b"RIFF"
        b"\x24\xd3\x05\x00"   # chunk size (irrelevant for fake)
        b"WAVE"
        b"fmt "
        b"\x10\x00\x00\x00"   # subchunk1 size = 16
        b"\x01\x00"            # PCM
        b"\x01\x00"            # mono
        b"\xc0\x5d\x00\x00"   # sample rate 24000
        b"\x80\xbb\x00\x00"   # byte rate
        b"\x02\x00"            # block align
        b"\x10\x00"            # bits per sample 16
        b"data"
        b"\x00\xd1\x05\x00"   # data size
        + b"\x00\x00" * 24000  # 1 second of silence
    )

    def __init__(self) -> None:
        self._call_count = 0

    async def synthesize(
        self,
        *,
        text: str,
        voice_profile: str | None,
    ) -> bytes:
        self._call_count += 1
        return self._FAKE_WAV

    @property
    def call_count(self) -> int:
        return self._call_count


class OpenAIManimNarrationService:
    """Synthesizes narration using an OpenAI-compatible TTS endpoint.

    Credentials are passed explicitly — never read from environment variables here.
    Reuses OpenAISpeechClient without importing RealSpeechExecutor.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        response_format: str = _DEFAULT_FORMAT,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._response_format = response_format
        self._client = None  # lazy-init to avoid requiring openai at import time

    def _get_client(self):
        if self._client is None:
            from learning_pipeline.tools.speech.client import OpenAISpeechClient
            self._client = OpenAISpeechClient(
                base_url=self._base_url,
                api_key=self._api_key,
            )
        return self._client

    async def synthesize(
        self,
        *,
        text: str,
        voice_profile: str | None,
    ) -> bytes:
        voice = _VOICE_REGISTRY.get(voice_profile or "default", _DEFAULT_VOICE)
        return await self._get_client().synthesize(
            text=text,
            voice=voice,
            model=self._model,
            response_format=self._response_format,
        )
