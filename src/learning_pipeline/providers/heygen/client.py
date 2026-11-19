"""Async HeyGen provider client.

Wraps the synchronous HeyGen REST API using asyncio.to_thread so all
blocking calls are isolated from the event loop.

Design constraints:
- Configuration is injected at construction; never read from the environment.
- load_dotenv() is not called at import time.
- API keys are never included in exception messages or logs.
- The polling loop is NOT here — polling requires persistent external state
  and belongs in the executor / ExternalOperationStore.
- Retries are NOT handled here — the WorkflowRunner owns retry policy.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

import httpx

from learning_pipeline.providers.heygen.errors import (
    HeyGenAuthenticationError,
    HeyGenConfigurationError,
    HeyGenDownloadError,
    HeyGenInvalidRequestError,
    HeyGenInvalidResponseError,
    HeyGenRateLimitError,
    HeyGenTransientError,
)
from learning_pipeline.providers.heygen.models import (
    HeyGenCreateVideoRequest,
    HeyGenCreateVideoResponse,
    HeyGenImageBackground,
    HeyGenUploadedAsset,
    HeyGenVideoStatus,
    ProviderVideoStatus,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.heygen.com"
_GENERATE_PATH = "/v2/video/generate"
_STATUS_PATH = "/v1/video_status.get"
_UPLOAD_PATH = "/v3/assets"

_CONTENT_TYPE_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_KNOWN_STATUSES = frozenset(s.value for s in ProviderVideoStatus)


# ── Protocol ──────────────────────────────────────────────────────────────────


@runtime_checkable
class HeyGenClientProtocol(Protocol):
    """Injectable HeyGen client interface used by RealAvatarVideoExecutor."""

    async def upload_asset(
        self,
        *,
        filename: str,
        data: bytes,
        media_type: str,
    ) -> HeyGenUploadedAsset: ...

    async def create_video(
        self,
        request: HeyGenCreateVideoRequest,
    ) -> HeyGenCreateVideoResponse: ...

    async def get_video_status(
        self,
        video_id: str,
    ) -> HeyGenVideoStatus: ...

    async def download_bytes(
        self,
        url: str,
    ) -> bytes: ...


# ── Real implementation ────────────────────────────────────────────────────────


class AsyncHeyGenClient:
    """Async wrapper over the HeyGen REST API using asyncio.to_thread.

    Parameters
    ----------
    api_key:
        HeyGen API key.  Must not be empty.
    request_timeout:
        Timeout in seconds for API requests (create, status, upload).
    download_timeout:
        Timeout in seconds for downloading video/subtitle bytes.
    """

    def __init__(
        self,
        *,
        api_key: str,
        request_timeout: float = 30.0,
        download_timeout: float = 300.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise HeyGenConfigurationError(
                "HeyGen API key must not be empty.  "
                "Set HEYGEN_API_KEY before constructing the client."
            )
        self._api_key = api_key
        self._request_timeout = request_timeout
        self._download_timeout = download_timeout

    def _auth_headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key}

    def _json_headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── upload_asset ──────────────────────────────────────────────────────────

    def _upload_asset_sync(
        self,
        *,
        filename: str,
        data: bytes,
        media_type: str,
    ) -> HeyGenUploadedAsset:
        try:
            resp = httpx.post(
                f"{_BASE_URL}{_UPLOAD_PATH}",
                headers=self._auth_headers(),
                files={"file": (filename, data, media_type)},
                timeout=self._request_timeout,
            )
        except httpx.TimeoutException as exc:
            raise HeyGenTransientError(f"Asset upload timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise HeyGenTransientError(f"Asset upload network error: {exc}") from exc

        self._raise_for_status(resp, context="upload_asset")

        try:
            asset_id = resp.json()["data"]["asset_id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise HeyGenInvalidResponseError(
                f"upload_asset: could not parse asset_id from response: {exc}"
            ) from exc

        logger.debug("Uploaded asset %s → %s", filename, asset_id)
        return HeyGenUploadedAsset(asset_id=asset_id)

    async def upload_asset(
        self,
        *,
        filename: str,
        data: bytes,
        media_type: str,
    ) -> HeyGenUploadedAsset:
        return await asyncio.to_thread(
            self._upload_asset_sync,
            filename=filename,
            data=data,
            media_type=media_type,
        )

    # ── create_video ──────────────────────────────────────────────────────────

    def _create_video_sync(
        self,
        request: HeyGenCreateVideoRequest,
    ) -> HeyGenCreateVideoResponse:
        payload = _serialise_create_request(request)
        try:
            resp = httpx.post(
                f"{_BASE_URL}{_GENERATE_PATH}",
                headers=self._json_headers(),
                json=payload,
                timeout=self._request_timeout,
            )
        except httpx.TimeoutException as exc:
            raise HeyGenTransientError(f"create_video timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise HeyGenTransientError(f"create_video network error: {exc}") from exc

        self._raise_for_status(resp, context="create_video")

        try:
            video_id = resp.json()["data"]["video_id"]
            if not video_id:
                raise ValueError("empty video_id")
        except (KeyError, TypeError, ValueError) as exc:
            raise HeyGenInvalidResponseError(
                f"create_video: could not parse video_id from response: {exc}"
            ) from exc

        logger.info("Submitted HeyGen video → video_id=%s", video_id)
        return HeyGenCreateVideoResponse(video_id=video_id)

    async def create_video(
        self,
        request: HeyGenCreateVideoRequest,
    ) -> HeyGenCreateVideoResponse:
        return await asyncio.to_thread(self._create_video_sync, request)

    # ── get_video_status ──────────────────────────────────────────────────────

    def _get_video_status_sync(self, video_id: str) -> HeyGenVideoStatus:
        try:
            resp = httpx.get(
                f"{_BASE_URL}{_STATUS_PATH}",
                headers=self._json_headers(),
                params={"video_id": video_id},
                timeout=self._request_timeout,
            )
        except httpx.TimeoutException as exc:
            raise HeyGenTransientError(f"get_video_status timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise HeyGenTransientError(f"get_video_status network error: {exc}") from exc

        self._raise_for_status(resp, context="get_video_status")

        try:
            data = resp.json().get("data", {})
        except (ValueError, AttributeError) as exc:
            raise HeyGenInvalidResponseError(
                f"get_video_status: could not parse JSON: {exc}"
            ) from exc

        raw_status = data.get("status", "unknown")
        status = (
            ProviderVideoStatus(raw_status)
            if raw_status in _KNOWN_STATUSES
            else ProviderVideoStatus.UNKNOWN
        )
        if raw_status not in _KNOWN_STATUSES:
            logger.warning("get_video_status: unknown provider status %r", raw_status)

        return HeyGenVideoStatus(
            video_id=video_id,
            status=status,
            video_url=data.get("video_url"),
            # HeyGen v2 currently exposes the SRT sidecar as caption_url.
            # Retain subtitle_url as a compatibility alias for older responses.
            subtitle_url=data.get("caption_url") or data.get("subtitle_url"),
            duration=data.get("duration"),
            error=data.get("error"),
        )

    async def get_video_status(self, video_id: str) -> HeyGenVideoStatus:
        return await asyncio.to_thread(self._get_video_status_sync, video_id)

    # ── download_bytes ────────────────────────────────────────────────────────

    def _download_bytes_sync(self, url: str) -> bytes:
        try:
            resp = httpx.get(url, timeout=self._download_timeout)
            resp.raise_for_status()
            return resp.content
        except httpx.TimeoutException as exc:
            raise HeyGenDownloadError(f"Download timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise HeyGenDownloadError(
                f"Download HTTP error {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise HeyGenDownloadError(f"Download network error: {exc}") from exc

    async def download_bytes(self, url: str) -> bytes:
        return await asyncio.to_thread(self._download_bytes_sync, url)

    # ── error classification ──────────────────────────────────────────────────

    @staticmethod
    def _raise_for_status(resp: httpx.Response, *, context: str) -> None:
        code = resp.status_code
        if code == 200:
            return
        if code == 401 or code == 403:
            raise HeyGenAuthenticationError(
                f"{context}: authentication failed (HTTP {code})"
            )
        if code == 400:
            try:
                detail = resp.json().get("error", {})
            except Exception:
                detail = resp.text[:200]
            raise HeyGenInvalidRequestError(
                f"{context}: bad request — {detail}"
            )
        if code == 404:
            raise HeyGenInvalidRequestError(
                f"{context}: endpoint not found (HTTP 404) — check API version"
            )
        if code == 429:
            raise HeyGenRateLimitError(
                f"{context}: rate limited (HTTP 429)"
            )
        if code >= 500:
            raise HeyGenTransientError(
                f"{context}: server error (HTTP {code})"
            )
        raise HeyGenInvalidResponseError(
            f"{context}: unexpected HTTP status {code}"
        )


# ── Serialisation helper ──────────────────────────────────────────────────────


def _serialise_create_request(req: HeyGenCreateVideoRequest) -> dict:
    """Convert HeyGenCreateVideoRequest to the HeyGen v2 wire format."""
    scenes = []
    for scene in req.video_inputs:
        bg = scene.background
        if isinstance(bg, HeyGenImageBackground):  # type: ignore[arg-type]
            background_dict = {
                "type": "image",
                "image_asset_id": bg.image_asset_id,
                "fit": bg.fit,
            }
        else:
            background_dict = {"type": "color", "value": bg.value}  # type: ignore[union-attr]

        scenes.append({
            "character": {
                "type": "avatar",
                "avatar_id": scene.character.avatar_id,
                "avatar_style": scene.character.avatar_style,
            },
            "voice": {
                "type": "text",
                "input_text": scene.voice.input_text,
                "voice_id": scene.voice.voice_id,
                "speed": scene.voice.speed,
            },
            "background": background_dict,
        })

    return {
        "video_inputs": scenes,
        "dimension": {
            "width": req.dimension.width,
            "height": req.dimension.height,
        },
        "caption": req.caption,
    }
