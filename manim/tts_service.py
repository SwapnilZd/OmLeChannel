"""LiteLLM-compatible TTS service for manim-voiceover.

LiteLLM's Vertex AI TTS proxy returns WAV audio (PCM 16-bit) regardless of
what the OpenAI TTS default implies. manim-voiceover's get_duration() checks
the file extension to choose between soundfile (WAV) and mutagen.MP3. Saving
with .mp3 extension but WAV content breaks mutagen.

This service subclasses OpenAIService and saves audio with .wav extension so
get_duration() routes to the soundfile WAVE reader correctly.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm_gateway import build_langfuse_headers, build_litellm_metadata, load_lite_llm_settings
from openai import OpenAI
from manim_voiceover.services.base import (
    DEFAULT_VOICEOVER_CACHE_JSON_FILENAME,
    append_voiceover_cache_entry,
)
from manim_voiceover.services.openai import OpenAIService
from manim_voiceover.helper import remove_bookmarks


class LiteLLMTTSService(OpenAIService):
    """OpenAIService variant that saves audio as .wav to match LiteLLM Vertex AI TTS output."""

    def prefetch(self, texts, *, max_workers=4):
        """Synthesize uncached narration concurrently and register it in the cache."""
        pending = []
        for text in texts:
            normalized = " ".join(text.split())
            input_data = self._input_data(normalized, speed=1.0)
            if self.get_cached_result(input_data, self.cache_dir) is None:
                pending.append(normalized)
        if not pending:
            return 0

        workers = max(1, min(int(max_workers), len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            entries = list(pool.map(self.generate_from_text, pending))

        cache_path = Path(self.cache_dir) / DEFAULT_VOICEOVER_CACHE_JSON_FILENAME
        for entry in entries:
            entry["final_audio"] = entry["original_audio"]
            append_voiceover_cache_entry(cache_path, entry)
        return len(entries)

    def _input_data(self, text, *, speed):
        return {
            "input_text": remove_bookmarks(text),
            "service": "litellm-wav",
            "config": {"voice": self.voice, "model": self.model, "speed": speed},
        }

    def generate_from_text(self, text, cache_dir=None, path=None, **kwargs):
        if cache_dir is None:
            cache_dir = self.cache_dir

        speed = kwargs.get("speed", 1.0)
        if not isinstance(speed, (int, float)):
            raise TypeError("speed must be a number")
        if not (0.25 <= speed <= 4.0):
            raise ValueError("The speed must be between 0.25 and 4.0.")

        input_data = self._input_data(text, speed=speed)
        input_text = input_data["input_text"]

        cached = self.get_cached_result(input_data, cache_dir)
        if cached is not None:
            return cached

        # Save as .wav — LiteLLM Vertex AI TTS returns WAV (PCM), and
        # manim-voiceover's get_duration() only uses the soundfile WAVE reader
        # when the filename ends with .wav.
        audio_path = self.get_audio_basename(input_data) + ".wav"

        connection = load_lite_llm_settings()
        client = OpenAI(
            base_url=connection.base_url,
            api_key=connection.api_key,
            max_retries=0,
            timeout=None,
        )
        with client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=self.voice,
            input=input_text,
            speed=speed,
            extra_body={
                "metadata": build_litellm_metadata(
                    self.model,
                    operation="synthesize",
                    job_id=os.environ.get("LLM_TELEMETRY_JOB_ID"),
                    task_id=os.environ.get("LLM_TELEMETRY_TASK_ID"),
                )
            },
            extra_headers=build_langfuse_headers(
                self.model,
                operation="synthesize",
                job_id=os.environ.get("LLM_TELEMETRY_JOB_ID"),
                task_id=os.environ.get("LLM_TELEMETRY_TASK_ID"),
            ),
        ) as response:
            response.stream_to_file(str(Path(cache_dir) / audio_path))

        return {
            "input_text": text,
            "input_data": input_data,
            "original_audio": audio_path,
        }
