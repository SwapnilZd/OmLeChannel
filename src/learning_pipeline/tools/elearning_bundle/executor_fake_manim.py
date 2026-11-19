"""FakeManimVideoExecutor — no Manim, no LLM, no TTS, deterministic output.

Validates AnimationBrief (same contract as the future real Phase 14C executor),
writes a minimal fake MP4 and WebVTT captions through ArtifactStore, and returns
a valid ManimVideoOutput.  No system dependencies beyond the main worker image.

Fake MP4 bytes contain minimal 1280×720 track metadata. They are not playable.
"""
from __future__ import annotations

import hashlib
from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactRef, ArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools._fake_media import fake_mp4_bytes
from learning_pipeline.tools.elearning_bundle.contracts import AnimationBrief, ManimVideoOutput
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError

_FAKE_MP4_BYTES = fake_mp4_bytes()

# Minimal valid WebVTT file.
_FAKE_VTT_BYTES = b"WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n[Placeholder narration]\n"


class FakeManimVideoExecutor:
    """Fake video.manim.render executor.

    Validates AnimationBrief, writes deterministic fake artifacts, and returns
    a fully valid ManimVideoOutput.  No Manim installation, LLM, or TTS calls.

    Parameters
    ----------
    artifact_store:
        Where to persist fake artifacts (required to test artifact URI generation).
    write_captions:
        If True (default), also write a fake VTT captions artifact.
    write_fake_artifacts:
        If True (default), write minimal fake bytes to the store.
        Set False when the test only needs contract validation.
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        write_captions: bool = True,
        write_fake_artifacts: bool = True,
    ) -> None:
        self._store = artifact_store
        self._write_captions = write_captions
        self._write = write_fake_artifacts

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # 1. Validate input contract
        try:
            brief = AnimationBrief.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid video.manim.render input: {exc}"
            ) from exc

        wf_id = context.workflow_id
        ns = f"manim/{wf_id}"
        anim_id = brief.animation_id

        captions_ref: ArtifactRef | None = None
        captions_uri: str | None = None

        if self._store is not None and self._write:
            video_ref = await self._store.put_bytes(
                namespace=ns,
                name=f"{anim_id}.mp4",
                data=_FAKE_MP4_BYTES,
                media_type="video/mp4",
            )
            video_uri = video_ref.uri

            if self._write_captions:
                captions_ref = await self._store.put_bytes(
                    namespace=ns,
                    name=f"{anim_id}.vtt",
                    data=_FAKE_VTT_BYTES,
                    media_type="text/vtt",
                )
                captions_uri = captions_ref.uri
        else:
            base = f"fake://manim/{wf_id}"
            mp4_sha = hashlib.sha256(_FAKE_MP4_BYTES).hexdigest()
            video_ref = ArtifactRef(
                uri=f"{base}/{anim_id}.mp4",
                media_type="video/mp4",
                sha256=mp4_sha,
                size_bytes=len(_FAKE_MP4_BYTES),
            )
            video_uri = video_ref.uri

            if self._write_captions:
                vtt_sha = hashlib.sha256(_FAKE_VTT_BYTES).hexdigest()
                captions_ref = ArtifactRef(
                    uri=f"{base}/{anim_id}.vtt",
                    media_type="text/vtt",
                    sha256=vtt_sha,
                    size_bytes=len(_FAKE_VTT_BYTES),
                )
                captions_uri = captions_ref.uri

        # 2. Build and validate output
        try:
            output = ManimVideoOutput(
                video=video_ref,
                video_uri=video_uri,
                captions=captions_ref,
                captions_uri=captions_uri,
                captions_media_type="text/vtt" if captions_ref else None,
                poster=None,
                poster_uri=None,
                generated_source=None,
                render_log=None,
                trace_uri=None,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{context.task_id}] ManimVideoOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()
