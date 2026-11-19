"""
Provider-independent speech client protocol and OpenAI-compatible adapter.

The rest of the application depends on SpeechClient, not on the OpenAI SDK.
The OpenAI SDK is only imported inside OpenAISpeechClient.__init__ so that
importing this module never requires the package to be installed (fake/test
mode never touches it).

The synchronous SDK call is offloaded with asyncio.to_thread so the async
workflow runner event loop is never blocked waiting on a provider request.
"""
from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from llm_gateway import build_langfuse_headers, build_litellm_metadata


@runtime_checkable
class SpeechClient(Protocol):
    """Provider-agnostic TTS interface."""

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        response_format: str,
    ) -> bytes: ...


class OpenAISpeechClient:
    """Adapts LiteLLM's OpenAI-compatible ``audio.speech.create`` endpoint."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "The openai package is required for real speech synthesis. "
                "Install it with: pip install 'openai>=2.45,<3'"
            ) from exc
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        response_format: str,
    ) -> bytes:
        def _call() -> bytes:
            response = self._client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format=response_format,
                extra_body={
                    "metadata": build_litellm_metadata(model, operation="synthesize")
                },
                extra_headers=build_langfuse_headers(model, operation="synthesize"),
            )
            return response.content

        return await asyncio.to_thread(_call)
