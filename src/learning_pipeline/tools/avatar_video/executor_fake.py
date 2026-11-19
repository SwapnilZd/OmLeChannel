"""FakeAvatarVideoExecutor — no credentials, no network, deterministic output.

Uses the exact same input/output contracts and task type as RealAvatarVideoExecutor.
Validates AvatarVideoRenderInput (same contract) and returns deterministic fake
artifact URIs through ArtifactStore.  Suitable for reference workflow tests,
unit tests, and CI pipelines that must not touch HeyGen.

Fake MP4 bytes contain a minimal ISO base-media box structure with 1280×720
track metadata. The placeholder is intentionally not playable.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools._fake_media import fake_mp4_bytes
from learning_pipeline.tools.avatar_video.contracts import (
    AvatarVideoRenderInput,
    AvatarVideoRenderOutput,
    AvatarVideoUsage,
)
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError

_FAKE_MP4_BYTES = fake_mp4_bytes()

_FAKE_SUBTITLE_BYTES = b"1\n00:00:00,000 --> 00:00:02,000\n[fake subtitle]\n"


class FakeAvatarVideoExecutor:
    """Fake video.avatar.render executor.

    Validates AvatarVideoRenderInput (same contract as RealAvatarVideoExecutor),
    writes deterministic fake artifacts through ArtifactStore, and returns a
    fully valid AvatarVideoRenderOutput dict.  No credentials or network access.

    Parameters
    ----------
    artifact_store:
        Where to persist fake artifacts (required to test artifact URI generation).
    delay:
        Artificial async delay in seconds (default 0) for concurrency tests.
    write_fake_artifacts:
        If True (default), write minimal fake MP4 bytes to the store.
        Set False when the test only needs contract validation.
    """

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        delay: float = 0.0,
        write_fake_artifacts: bool = True,
    ) -> None:
        self._store = artifact_store
        self._delay = delay
        self._write = write_fake_artifacts

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # 1. Validate input contract
        try:
            inp = AvatarVideoRenderInput.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid video.avatar.render input: {exc}"
            ) from exc

        if self._delay:
            await asyncio.sleep(self._delay)

        wf_id = context.workflow_id
        task_id = context.task_id

        # 2. Write deterministic fake artifacts (if a store is available)
        if self._store is not None and self._write:
            video_ref = await self._store.put_bytes(
                namespace=f"deliverables/{wf_id}",
                name=f"{inp.deliverable_id}.mp4",
                data=_FAKE_MP4_BYTES,
                media_type="video/mp4",
            )
            video_uri = video_ref.uri

            subtitle_uri: str | None = None
            if inp.captions:
                sub_ref = await self._store.put_bytes(
                    namespace=f"deliverables/{wf_id}",
                    name=f"{inp.deliverable_id}.srt",
                    data=_FAKE_SUBTITLE_BYTES,
                    media_type="text/srt",
                )
                subtitle_uri = sub_ref.uri

            cost_report = {"fake": True, "task_id": task_id}
            cost_ref = await self._store.put_bytes(
                namespace=f"deliverables/{wf_id}",
                name=f"{inp.deliverable_id}.costs.json",
                data=json.dumps(cost_report).encode(),
                media_type="application/json",
            )
            cost_report_uri = cost_ref.uri
        else:
            # No store — return fake:// URIs (suitable for runner tests that
            # don't need to verify artifact content)
            base = f"fake://deliverables/{wf_id}"
            video_uri = f"{base}/{inp.deliverable_id}.mp4"
            subtitle_uri = f"{base}/{inp.deliverable_id}.srt" if inp.captions else None
            cost_report_uri = f"{base}/{inp.deliverable_id}.costs.json"

        # 3. Estimate duration from scene hints
        total_estimated = sum(
            s.estimated_duration_seconds
            for s in inp.scenes
            if s.estimated_duration_seconds is not None
        )
        duration_seconds: float | None = total_estimated if total_estimated > 0 else None

        # 4. Build usage
        usage = AvatarVideoUsage(
            scene_count=len(inp.scenes),
            estimated_duration_seconds=duration_seconds,
            actual_duration_seconds=None,
            uploaded_asset_count=0,
            estimated_credits=None,
            estimated_cost_usd=None,
        )

        # 5. Validate and return output
        try:
            output = AvatarVideoRenderOutput(
                deliverable_id=inp.deliverable_id,
                provider_operation_id=f"fake-video-id-{task_id}",
                video_uri=video_uri,
                subtitle_uri=subtitle_uri,
                subtitle_media_type="text/srt" if subtitle_uri else None,
                cost_report_uri=cost_report_uri,
                media_type="video/mp4",
                duration_seconds=duration_seconds,
                usage=usage,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{task_id}] AvatarVideoRenderOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()
