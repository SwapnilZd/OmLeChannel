"""RealAvatarVideoExecutor — HeyGen avatar-video production executor.

Responsibilities (in order):
 1. Validate AvatarVideoRenderInput.
 2. Resolve logical avatar and voice profiles to provider IDs.
 3. Hash the validated input for idempotency.
 4. Look up or create a durable ExternalOperationCheckpoint.
 5. If no checkpoint: upload input assets, map request, submit to HeyGen.
 6. Persist the returned video_id before polling begins.
 7. Poll HeyGen asynchronously (non-blocking) until completed or failed.
 8. On completed: download MP4 bytes, validate, and persist via ArtifactStore.
 9. Optionally download subtitle bytes and persist.
10. Calculate usage and estimated cost.
11. Write a JSON cost report artifact.
12. Validate AvatarVideoRenderOutput and return model_dump().

Not responsible for:
- Invoking the Video Workflow Planner.
- Changing scene order.
- Generating new scene scripts.
- Adding workflow jobs.
- Querying mutable RLO content.
- Writing to arbitrary filesystem paths.
- Re-submitting on every retry.
- Using an LLM.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Callable

from learning_pipeline.media_validation import MP4DimensionError, validate_mp4_dimensions
from learning_pipeline.providers.heygen.asset_cache import ProviderAssetCache, compute_sha256
from learning_pipeline.providers.heygen.client import HeyGenClientProtocol
from learning_pipeline.providers.heygen.errors import (
    HeyGenOperationFailedError,
    HeyGenOperationTimeoutError,
    HeyGenTransientError,
)
from learning_pipeline.providers.heygen.mapper import HeyGenSceneMapper
from learning_pipeline.providers.heygen.models import ProviderVideoStatus
from learning_pipeline.providers.heygen.operation_store import (
    ExternalOperationCheckpoint,
    ExternalOperationStore,
    make_checkpoint,
    utc_now_iso,
)
from learning_pipeline.runtime.artifact_store import ArtifactStore, ArtifactWriteError
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.avatar_video.contracts import (
    AvatarVideoRenderInput,
    AvatarVideoRenderOutput,
    AvatarVideoUsage,
    ImageBackground,
)
from learning_pipeline.tools.avatar_video.pricing import HeyGenPricingConfig
from learning_pipeline.tools.avatar_video.profiles import HeyGenProfileRegistry
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError

logger = logging.getLogger(__name__)

# Minimal ISO base-media ftyp box marker (first 4 bytes of box_size + "ftyp")
_FTYP_SIGNATURE = b"ftyp"
# Maximum MP4 artifact size accepted (500 MB)
_MAX_MP4_SIZE_BYTES = 500 * 1024 * 1024

_DEFAULT_POLL_INTERVAL = 15.0
_DEFAULT_MAX_WAIT = 1800.0
_DEFAULT_STATUS_TIMEOUT = 15.0
_DEFAULT_DOWNLOAD_TIMEOUT = 300.0
_SRT_TIMING_RE = re.compile(
    rb"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}"
)


class RealAvatarVideoExecutor:
    """Production executor for ``video.avatar.render`` using HeyGen.

    All long-running I/O is awaited non-blockingly.  ``asyncio.sleep``
    is used for polling, never ``time.sleep``.

    Parameters
    ----------
    client:
        Injected HeyGen client (``HeyGenClientProtocol``).
    artifact_store:
        Where to read input assets and write output artifacts.
    profile_registry:
        Resolves logical avatar/voice profile names to provider IDs.
    operation_store:
        Persists external-operation checkpoints for retry safety.
    asset_cache:
        Avoids duplicate asset uploads on retries.
    scene_mapper:
        Maps provider-neutral input to HeyGen wire format.
    pricing:
        Pricing configuration for cost estimation.
    poll_interval:
        Seconds between HeyGen status checks.
    max_poll_wait:
        Maximum seconds to poll before raising HeyGenOperationTimeoutError.
    sleep_fn:
        Injectable sleep callable for tests (default: asyncio.sleep).
    """

    def __init__(
        self,
        *,
        client: HeyGenClientProtocol,
        artifact_store: ArtifactStore,
        profile_registry: HeyGenProfileRegistry,
        operation_store: ExternalOperationStore,
        asset_cache: ProviderAssetCache,
        scene_mapper: HeyGenSceneMapper,
        pricing: HeyGenPricingConfig,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        max_poll_wait: float = _DEFAULT_MAX_WAIT,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        self._client = client
        self._store = artifact_store
        self._profiles = profile_registry
        self._op_store = operation_store
        self._asset_cache = asset_cache
        self._mapper = scene_mapper
        self._pricing = pricing
        self._poll_interval = poll_interval
        self._max_poll_wait = max_poll_wait
        self._sleep = sleep_fn or asyncio.sleep

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        wf_id = context.workflow_id
        task_id = context.task_id

        # 1. Validate input
        try:
            inp = AvatarVideoRenderInput.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{task_id}] Invalid video.avatar.render input: {exc}"
            ) from exc

        # 2. Resolve profiles
        avatar_profile = self._profiles.resolve_avatar(inp.avatar.profile)
        voice_profile = self._profiles.resolve_voice(inp.voice.profile)

        # 3. Stable input hash for idempotency
        input_hash = _hash_render_input(inp)

        # 4. Check for existing checkpoint
        checkpoint = await self._op_store.get(wf_id, task_id)
        video_id: str

        if checkpoint is not None:
            # Retry path
            if checkpoint.input_hash != input_hash:
                raise InvalidToolInputError(
                    f"[{task_id}] Input hash mismatch on retry: "
                    f"stored={checkpoint.input_hash!r}, current={input_hash!r}. "
                    "A different input was submitted for the same task on retry."
                )
            if checkpoint.status == ProviderVideoStatus.COMPLETED:
                # Already completed — skip to download/persist step
                logger.info("[%s] Checkpoint shows completed; re-downloading result.", task_id)
                video_id = checkpoint.operation_id
                return await self._finalise_completed(
                    inp=inp,
                    video_id=video_id,
                    wf_id=wf_id,
                    task_id=task_id,
                    upload_count=int(
                        checkpoint.provider_metadata.get("upload_count", 0)
                    ),
                )
            logger.info(
                "[%s] Resuming existing HeyGen operation %s (status=%s)",
                task_id,
                checkpoint.operation_id,
                checkpoint.status,
            )
            video_id = checkpoint.operation_id
        else:
            # First submission path
            # 5. Upload input assets and map request
            upload_count, resolved_assets = await self._upload_assets(
                inp, wf_id, task_id
            )
            heygen_request = self._mapper.map_request(
                inp, resolved_assets, avatar_profile, voice_profile
            )

            # 6. Submit to HeyGen
            response = await self._client.create_video(heygen_request)
            video_id = response.video_id
            logger.info("[%s] Submitted to HeyGen → video_id=%s", task_id, video_id)

            # 7. Persist checkpoint IMMEDIATELY before polling
            checkpoint = make_checkpoint(
                workflow_id=wf_id,
                task_id=task_id,
                operation_id=video_id,
                input_hash=input_hash,
                status=ProviderVideoStatus.PENDING,
            )
            checkpoint = _update_checkpoint(
                checkpoint,
                status=ProviderVideoStatus.PENDING,
                metadata={"upload_count": upload_count},
            )
            await self._op_store.save(checkpoint)
            upload_count_for_cost = upload_count

        # 8. Poll asynchronously until terminal state
        final_status = await self._poll(
            video_id=video_id,
            wf_id=wf_id,
            task_id=task_id,
            existing_checkpoint=checkpoint,
        )

        if final_status.status == ProviderVideoStatus.FAILED:
            await self._op_store.save(
                _update_checkpoint(checkpoint, status=ProviderVideoStatus.FAILED)
            )
            raise HeyGenOperationFailedError(
                f"[{task_id}] HeyGen render failed for video_id={video_id}: "
                f"{final_status.error or 'no error detail'}"
            )

        # Mark as completed in checkpoint
        upload_count_for_cost = int(
            checkpoint.provider_metadata.get("upload_count", 0)
        )
        await self._op_store.save(
            _update_checkpoint(
                checkpoint,
                status=ProviderVideoStatus.COMPLETED,
                metadata={"upload_count": upload_count_for_cost},
            )
        )

        return await self._finalise_completed(
            inp=inp,
            video_id=video_id,
            wf_id=wf_id,
            task_id=task_id,
            upload_count=upload_count_for_cost,
            provider_duration=final_status.duration,
            provider_video_url=final_status.video_url,
            provider_subtitle_url=final_status.subtitle_url,
        )

    # ── Asset upload ──────────────────────────────────────────────────────────

    async def _upload_assets(
        self,
        inp: AvatarVideoRenderInput,
        wf_id: str,
        task_id: str,
    ) -> tuple[int, dict[str, str]]:
        """Upload all image/video background assets; return (upload_count, asset_id_map)."""
        resolved: dict[str, str] = {}
        upload_count = 0

        for scene in inp.scenes:
            bg = scene.background
            if not isinstance(bg, ImageBackground):
                continue
            artifact_uri = bg.artifact_uri
            if artifact_uri in resolved:
                continue  # already uploaded this run

            # Read artifact bytes from store
            asset_bytes = await self._store.get_bytes(artifact_uri)
            sha256 = compute_sha256(asset_bytes)

            # Check cache first
            cached = await asyncio.to_thread(
                self._asset_cache.get, artifact_uri, sha256
            )
            if cached is not None:
                logger.debug(
                    "[%s] Reusing cached asset_id=%s for %s",
                    task_id, cached.provider_asset_id, artifact_uri,
                )
                resolved[artifact_uri] = cached.provider_asset_id
                continue

            # Upload to HeyGen
            filename = artifact_uri.rsplit("/", 1)[-1] or "background.png"
            media_type = _guess_media_type(filename)
            uploaded = await self._client.upload_asset(
                filename=filename,
                data=asset_bytes,
                media_type=media_type,
            )
            await asyncio.to_thread(
                self._asset_cache.put, artifact_uri, sha256, uploaded.asset_id
            )
            resolved[artifact_uri] = uploaded.asset_id
            upload_count += 1
            logger.info(
                "[%s] Uploaded %s → asset_id=%s", task_id, artifact_uri, uploaded.asset_id
            )

        return upload_count, resolved

    # ── Polling ───────────────────────────────────────────────────────────────

    async def _poll(
        self,
        video_id: str,
        wf_id: str,
        task_id: str,
        existing_checkpoint: ExternalOperationCheckpoint,
    ):
        """Poll HeyGen until a terminal state is reached.

        Uses ``asyncio.sleep`` — never blocks the event loop.
        Preserves video_id on timeout so a retry can resume.
        """
        from learning_pipeline.providers.heygen.models import HeyGenVideoStatus

        elapsed = 0.0
        attempt = 0
        checkpoint = existing_checkpoint

        while elapsed < self._max_poll_wait:
            attempt += 1
            status = await self._client.get_video_status(video_id)
            logger.info(
                "[%s] Poll attempt %d | elapsed=%.0fs | status=%s",
                task_id, attempt, elapsed, status.status,
            )

            # Persist latest status
            checkpoint = _update_checkpoint(
                checkpoint,
                status=status.status,
                last_checked=utc_now_iso(),
            )
            await self._op_store.save(checkpoint)

            if status.status in (
                ProviderVideoStatus.COMPLETED,
                ProviderVideoStatus.FAILED,
            ):
                return status

            if status.status == ProviderVideoStatus.UNKNOWN:
                logger.warning(
                    "[%s] Unknown provider status — continuing to poll.", task_id
                )

            await self._sleep(self._poll_interval)
            elapsed += self._poll_interval

        # Timeout — preserve video_id in checkpoint so retry can resume
        await self._op_store.save(
            _update_checkpoint(
                checkpoint,
                status="timeout",
                last_checked=utc_now_iso(),
            )
        )
        raise HeyGenOperationTimeoutError(
            f"[{task_id}] HeyGen video {video_id} did not complete within "
            f"{self._max_poll_wait}s ({attempt} polls).",
            provider_video_id=video_id,
        )

    # ── Finalise (download, validate, persist, cost) ──────────────────────────

    async def _finalise_completed(
        self,
        *,
        inp: AvatarVideoRenderInput,
        video_id: str,
        wf_id: str,
        task_id: str,
        upload_count: int,
        provider_duration: float | None = None,
        provider_video_url: str | None = None,
        provider_subtitle_url: str | None = None,
    ) -> dict[str, Any]:
        # Fetch final status if URLs are not yet known
        if provider_video_url is None:
            final_status = await self._client.get_video_status(video_id)
            provider_video_url = final_status.video_url
            provider_subtitle_url = final_status.subtitle_url
            if provider_duration is None:
                provider_duration = final_status.duration

        if not provider_video_url:
            raise HeyGenTransientError(
                f"[{task_id}] HeyGen returned no video_url for completed video {video_id}"
            )
        if inp.captions and not provider_subtitle_url:
            raise HeyGenTransientError(
                f"[{task_id}] HeyGen returned no caption_url for completed video "
                f"{video_id} even though captions were required."
            )

        # Download MP4 (do not keep the temporary URL as the deliverable)
        mp4_bytes = await self._client.download_bytes(provider_video_url)
        _validate_mp4(
            mp4_bytes,
            task_id=task_id,
            expected_width=inp.dimensions.width,
            expected_height=inp.dimensions.height,
        )

        # Inspect actual duration from bytes if possible (basic: trust provider)
        # Provider-reported duration is preferred over generation latency.
        # If unavailable, report None rather than fabricate.
        actual_duration = provider_duration  # float | None

        # Persist MP4 artifact
        try:
            video_ref = await self._store.put_bytes(
                namespace=f"deliverables/{wf_id}",
                name=f"{inp.deliverable_id}.mp4",
                data=mp4_bytes,
                media_type="video/mp4",
            )
        except ArtifactWriteError as exc:
            raise ArtifactWriteError(
                f"[{task_id}] Failed to persist MP4 artifact: {exc}"
            ) from exc

        # Download and persist subtitles if requested and available
        subtitle_uri: str | None = None
        if inp.captions and provider_subtitle_url:
            sub_bytes = await self._client.download_bytes(provider_subtitle_url)
            _validate_subtitle(sub_bytes, task_id=task_id)
            try:
                sub_ref = await self._store.put_bytes(
                    namespace=f"deliverables/{wf_id}",
                    name=f"{inp.deliverable_id}.srt",
                    data=sub_bytes,
                    media_type="text/srt",
                )
                subtitle_uri = sub_ref.uri
            except ArtifactWriteError as exc:
                raise ArtifactWriteError(
                    f"[{task_id}] Failed to persist subtitle artifact: {exc}"
                ) from exc

        # Cost estimation
        estimated_seconds = sum(
            s.estimated_duration_seconds
            for s in inp.scenes
            if s.estimated_duration_seconds is not None
        ) or None
        estimated_credits = self._pricing.estimate_credits(
            duration_seconds=actual_duration,
            upload_count=upload_count,
        )
        estimated_cost_usd = self._pricing.estimate_cost_usd(
            duration_seconds=actual_duration,
            upload_count=upload_count,
        )
        usage = AvatarVideoUsage(
            scene_count=len(inp.scenes),
            estimated_duration_seconds=estimated_seconds,
            actual_duration_seconds=actual_duration,
            uploaded_asset_count=upload_count,
            estimated_credits=estimated_credits,
            estimated_cost_usd=estimated_cost_usd,
        )

        # Write cost report artifact
        cost_report = {
            "deliverable_id": inp.deliverable_id,
            "video_id": video_id,
            "pricing_version": self._pricing.pricing_version,
            "engine": self._pricing.engine,
            "scene_count": usage.scene_count,
            "estimated_duration_seconds": usage.estimated_duration_seconds,
            "actual_duration_seconds": usage.actual_duration_seconds,
            "uploaded_asset_count": usage.uploaded_asset_count,
            "estimated_credits": usage.estimated_credits,
            "estimated_cost_usd": usage.estimated_cost_usd,
            "note": (
                "Pricing is observational. Verify against current HeyGen pricing "
                "before using for billing."
            ),
        }
        try:
            cost_ref = await self._store.put_bytes(
                namespace=f"deliverables/{wf_id}",
                name=f"{inp.deliverable_id}.costs.json",
                data=json.dumps(cost_report, indent=2).encode(),
                media_type="application/json",
            )
        except ArtifactWriteError as exc:
            raise ArtifactWriteError(
                f"[{task_id}] Failed to persist cost report: {exc}"
            ) from exc

        # Validate and return output
        try:
            output = AvatarVideoRenderOutput(
                deliverable_id=inp.deliverable_id,
                provider_operation_id=video_id,
                video_uri=video_ref.uri,
                subtitle_uri=subtitle_uri,
                subtitle_media_type="text/srt" if subtitle_uri else None,
                cost_report_uri=cost_ref.uri,
                media_type="video/mp4",
                duration_seconds=actual_duration,
                usage=usage,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{task_id}] AvatarVideoRenderOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()


# ── Private helpers ───────────────────────────────────────────────────────────


def _hash_render_input(inp: AvatarVideoRenderInput) -> str:
    """Stable deterministic hash of a validated render input."""
    serialised = inp.model_dump_json()
    return hashlib.sha256(serialised.encode()).hexdigest()


def _validate_mp4(
    data: bytes,
    *,
    task_id: str,
    expected_width: int,
    expected_height: int,
) -> None:
    """Validate MP4 structure and require the dimensions requested from HeyGen."""
    if not data:
        raise HeyGenTransientError(
            f"[{task_id}] Downloaded MP4 is empty."
        )
    if len(data) > _MAX_MP4_SIZE_BYTES:
        raise HeyGenTransientError(
            f"[{task_id}] Downloaded MP4 exceeds maximum size "
            f"({len(data) // (1024*1024)}MB > {_MAX_MP4_SIZE_BYTES // (1024*1024)}MB)."
        )
    # ISO base-media: first box begins at byte 0; bytes 4–8 contain the box type.
    # A valid MP4 should have an "ftyp" box in the first 32 bytes.
    header = data[:32]
    if _FTYP_SIGNATURE not in header:
        raise HeyGenTransientError(
            f"[{task_id}] Downloaded bytes do not appear to be a valid MP4 "
            "(no ftyp box found in first 32 bytes)."
        )
    try:
        validate_mp4_dimensions(
            data,
            expected_width=expected_width,
            expected_height=expected_height,
        )
    except MP4DimensionError as exc:
        raise HeyGenTransientError(
            f"[{task_id}] HeyGen returned invalid video dimensions: {exc}"
        ) from exc


def _validate_subtitle(data: bytes, *, task_id: str) -> None:
    """Validate that HeyGen returned a non-empty UTF-8 SRT with timed cues."""
    if not data:
        raise HeyGenTransientError(f"[{task_id}] Downloaded subtitle file is empty.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HeyGenTransientError(
            f"[{task_id}] Downloaded subtitle file is not valid UTF-8."
        ) from exc
    if not _SRT_TIMING_RE.search(data):
        raise HeyGenTransientError(
            f"[{task_id}] Downloaded subtitle file is not valid SRT: "
            "no timed cue was found."
        )


def _guess_media_type(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mapping = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    return mapping.get(suffix, "image/jpeg")


def _update_checkpoint(
    checkpoint: ExternalOperationCheckpoint,
    *,
    status: str | ProviderVideoStatus | None = None,
    last_checked: str | None = None,
    metadata: dict | None = None,
) -> ExternalOperationCheckpoint:
    """Return a new checkpoint with updated fields (FrozenModel is immutable)."""
    data = checkpoint.model_dump()
    if status is not None:
        data["status"] = str(status)
    if last_checked is not None:
        data["last_checked_at"] = last_checked
    if metadata is not None:
        merged = {**data.get("provider_metadata", {}), **metadata}
        data["provider_metadata"] = merged
    return ExternalOperationCheckpoint.model_validate(data)
