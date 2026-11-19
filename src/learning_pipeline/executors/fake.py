"""
Fake executors — no network, no credentials, deterministic output.

FakeSpeechExecutor validates inputs against SpeechSynthesisInput (the same
typed contract as RealSpeechExecutor) and returns a fake artifact URI so
the BuildPlan works identically in both EXECUTOR_MODE=fake and EXECUTOR_MODE=real.

FakeAudioAssemblyExecutor is a stub until Phase 8.
"""
from __future__ import annotations

import asyncio
from typing import Any

from learning_pipeline.runtime.execution import ExecutionContext


class FakeSpeechExecutor:
    """Fake speech.synthesize executor.

    Validates SpeechSynthesisInput (same contract as RealSpeechExecutor) and
    returns a deterministic fake URI.  No TTS call is made.  Awaits a
    configurable delay so concurrent scheduling can be verified by tests.
    """

    def __init__(self, delay: float = 0.01) -> None:
        self._delay = delay

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        from learning_pipeline.tools.speech.contracts import SpeechSynthesisInput

        inp = SpeechSynthesisInput.model_validate(context.inputs)
        await asyncio.sleep(self._delay)

        return {
            "audio_uri": f"fake://audio/{context.task_id}.wav",
            "media_type": "audio/wav",
            "duration_seconds": 1.0,
            "speaker": inp.speaker,
            "voice": inp.voice_hint or "fake-voice",
            "usage": {
                "input_characters": len(inp.text),
                "input_tokens_estimate": round(len(inp.text) / 4, 1),
                "audio_duration_seconds": 1.0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "total_cost_usd": 0.0,
            },
        }


class FakeAudioAssemblyExecutor:
    """Fake audio.assemble executor.

    Validates AudioAssemblyInput (same contract as RealAudioAssemblyExecutor)
    and returns deterministic fake artifact URIs.  No audio I/O is performed.
    """

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        from learning_pipeline.tools.audio_assembly.contracts import AudioAssemblyInput

        inp = AudioAssemblyInput.model_validate(context.inputs)
        await asyncio.sleep(0)
        did = inp.deliverable_id
        base = f"fake://deliverables/{context.workflow_id}"
        n = len(inp.segments)
        # Aggregate available usage without touching the artifact store
        total_chars = sum(
            s.usage.input_characters for s in inp.segments if s.usage is not None
        )
        return {
            "deliverable_id": did,
            "audio_uri": f"{base}/{did}.wav",
            "costs_uri": f"{base}/{did}.costs.json",
            "media_type": "audio/wav",
            "duration_seconds": float(n),
            "segment_count": n,
            "usage": {
                "total_input_characters": total_chars,
                "total_input_tokens_estimate": 0.0,
                "total_audio_duration_seconds": float(n),
                "total_pause_duration_seconds": 0.0,
                "total_input_cost_usd": 0.0,
                "total_output_cost_usd": 0.0,
                "total_cost_usd": 0.0,
            },
        }
