"""
RealAudioAssemblyExecutor — production audio.assemble implementation.

Responsibilities (in order):
1.  Validate task inputs with AudioAssemblyInput.
2.  Read each segment WAV through the injected ArtifactStore.
3.  Validate that every artifact is a readable WAV.
4.  Verify format compatibility across all speech segments.
5.  Preserve the declared segment order (not completion order).
6.  Insert silence according to the pause policy.
7.  Concatenate all WAV frames into one output WAV.
8.  Validate the assembled WAV.
9.  Aggregate usage and cost records from segment metadata.
10. Store the final WAV through ArtifactStore.
11. Build and store the costs/usage JSON artifact.
12. Validate and return AudioAssemblyOutput as a dict.

Pause policy
------------
Between adjacent segments N and N+1:
    effective pause = segment[N].pause_after_seconds + default_gap_seconds

After the final segment:
    effective pause = final_segment.pause_after_seconds   (no extra default gap)

Not responsible for: TTS calls, replanning, DB writes, retries, ordering decisions.
"""
from __future__ import annotations

import json
from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactNotFoundError, ArtifactStore
from learning_pipeline.tools.audio_utils import (
    IncompatibleWavError,
    check_wav_compatibility,
    concat_wavs,
    make_silence,
    wav_duration_seconds,
)
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.audio_assembly.contracts import (
    AudioAssemblyInput,
    AudioAssemblyOutput,
    AudioAssemblySegment,
    PodcastUsageSummary,
)
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError
from learning_pipeline.tools.speech.contracts import SpeechUsage


class AudioAssemblyError(RuntimeError):
    """A segment artifact could not be read or is invalid."""


class IncompatibleSegmentError(ValueError):
    """Segment WAVs have incompatible audio formats."""


def _effective_pause(seg: AudioAssemblySegment, is_last: bool, default_gap: float) -> float:
    """Return the silence to insert after ``seg``.

    Between adjacent segments: seg.pause_after_seconds + default_gap_seconds.
    After the final segment: seg.pause_after_seconds only (no extra default gap).
    """
    if is_last:
        return seg.pause_after_seconds
    return seg.pause_after_seconds + default_gap


def _build_usage_summary(
    segments: tuple[AudioAssemblySegment, ...],
    spoken_seconds: float,
    pause_seconds: float,
) -> PodcastUsageSummary:
    total_chars = 0
    total_tokens = 0.0
    total_audio = 0.0
    total_in_cost = 0.0
    total_out_cost = 0.0

    for seg in segments:
        if seg.usage is not None:
            total_chars += seg.usage.input_characters
            total_tokens += seg.usage.input_tokens_estimate
            total_audio += seg.usage.audio_duration_seconds
            total_in_cost += seg.usage.input_cost_usd
            total_out_cost += seg.usage.output_cost_usd

    total_cost = total_in_cost + total_out_cost
    return PodcastUsageSummary(
        total_input_characters=total_chars,
        total_input_tokens_estimate=round(total_tokens, 1),
        total_audio_duration_seconds=round(total_audio or spoken_seconds, 3),
        total_pause_duration_seconds=round(pause_seconds, 3),
        total_input_cost_usd=round(total_in_cost, 6),
        total_output_cost_usd=round(total_out_cost, 6),
        total_cost_usd=round(total_cost, 6),
    )


def _build_cost_report(
    inp: AudioAssemblyInput,
    segments: tuple[AudioAssemblySegment, ...],
    segment_durations: list[float],
    pauses: list[float],
    final_duration: float,
    usage_summary: PodcastUsageSummary,
) -> dict:
    segment_records = []
    for seg, dur, pause in zip(segments, segment_durations, pauses):
        u = seg.usage
        record: dict[str, Any] = {
            "segment_id": seg.segment_id,
            "speaker": seg.speaker,
            "audio_uri": seg.audio_uri,
            "spoken_duration_seconds": round(dur, 3),
            "pause_after_seconds": round(pause, 3),
        }
        if u is not None:
            record.update(
                {
                    "input_characters": u.input_characters,
                    "input_tokens_estimate": u.input_tokens_estimate,
                    "input_cost_usd": u.input_cost_usd,
                    "output_cost_usd": u.output_cost_usd,
                    "total_segment_cost_usd": u.total_cost_usd,
                }
            )
        segment_records.append(record)

    return {
        "deliverable_id": inp.deliverable_id,
        "segment_count": len(segments),
        "total_input_characters": usage_summary.total_input_characters,
        "total_input_tokens_estimate": usage_summary.total_input_tokens_estimate,
        "total_spoken_audio_duration_seconds": usage_summary.total_audio_duration_seconds,
        "total_pause_duration_seconds": usage_summary.total_pause_duration_seconds,
        "final_deliverable_duration_seconds": round(final_duration, 3),
        "total_input_cost_usd": usage_summary.total_input_cost_usd,
        "total_output_cost_usd": usage_summary.total_output_cost_usd,
        "total_cost_usd": usage_summary.total_cost_usd,
        "segments": segment_records,
    }


class RealAudioAssemblyExecutor:
    """Production executor for ``audio.assemble``."""

    def __init__(self, *, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # 1. Validate input contract
        try:
            inp = AudioAssemblyInput.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid audio.assemble input: {exc}"
            ) from exc

        # 2. Read all segment WAVs through ArtifactStore
        segment_wavs: list[bytes] = []
        for seg in inp.segments:
            try:
                wav_bytes = await self._store.get_bytes(seg.audio_uri)
            except ArtifactNotFoundError as exc:
                raise AudioAssemblyError(
                    f"[{context.task_id}] Segment {seg.segment_id!r}: "
                    f"artifact not found: {seg.audio_uri!r}"
                ) from exc
            except Exception as exc:
                raise AudioAssemblyError(
                    f"[{context.task_id}] Segment {seg.segment_id!r}: "
                    f"read error: {exc}"
                ) from exc
            segment_wavs.append(wav_bytes)

        # 3–4. Validate format compatibility (fail before writing any output)
        try:
            params = check_wav_compatibility(segment_wavs)
        except IncompatibleWavError as exc:
            raise IncompatibleSegmentError(
                f"[{context.task_id}] Incompatible WAV formats: {exc}"
            ) from exc
        except Exception as exc:
            raise AudioAssemblyError(
                f"[{context.task_id}] WAV validation error: {exc}"
            ) from exc

        # 5–8. Assemble in declared order with pauses
        all_pieces: list[bytes] = []
        segment_durations: list[float] = []
        effective_pauses: list[float] = []
        total_pause = 0.0

        for i, (seg, wav_bytes) in enumerate(zip(inp.segments, segment_wavs)):
            all_pieces.append(wav_bytes)
            segment_durations.append(wav_duration_seconds(wav_bytes))

            is_last = i == len(inp.segments) - 1
            pause = _effective_pause(seg, is_last, inp.default_gap_seconds)
            effective_pauses.append(pause)

            if pause > 0:
                silence = make_silence(
                    pause,
                    sample_rate=params.framerate,
                    channels=params.nchannels,
                    sample_width=params.sampwidth,
                )
                all_pieces.append(silence)
                total_pause += pause

        final_wav = concat_wavs(all_pieces)

        # 9. Validate assembled WAV
        try:
            final_duration = wav_duration_seconds(final_wav)
        except Exception as exc:
            raise AudioAssemblyError(
                f"[{context.task_id}] Assembled WAV is invalid: {exc}"
            ) from exc

        # 10. Aggregate usage
        spoken_seconds = sum(segment_durations)
        usage_summary = _build_usage_summary(inp.segments, spoken_seconds, total_pause)

        # 11. Build cost report
        cost_report = _build_cost_report(
            inp, inp.segments, segment_durations, effective_pauses, final_duration, usage_summary
        )

        # 12. Store artifacts (both writes must succeed before returning success)
        namespace = f"deliverables/{context.workflow_id}"
        filename = inp.output_filename or f"{inp.deliverable_id}.wav"
        costs_filename = f"{inp.deliverable_id}.costs.json"

        wav_ref = await self._store.put_bytes(namespace, filename, final_wav, "audio/wav")
        costs_bytes = json.dumps(cost_report, indent=2).encode("utf-8")
        costs_ref = await self._store.put_bytes(
            namespace, costs_filename, costs_bytes, "application/json"
        )

        # 13. Validate output contract
        try:
            output = AudioAssemblyOutput(
                deliverable_id=inp.deliverable_id,
                audio_uri=wav_ref.uri,
                costs_uri=costs_ref.uri,
                media_type="audio/wav",
                duration_seconds=round(final_duration, 3),
                segment_count=len(inp.segments),
                usage=usage_summary,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{context.task_id}] AudioAssemblyOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()
