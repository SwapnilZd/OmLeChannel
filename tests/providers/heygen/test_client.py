"""Tests for AsyncHeyGenClient — mocked HTTP transport, no real API calls."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from learning_pipeline.providers.heygen.client import AsyncHeyGenClient, _serialise_create_request
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
    HeyGenAvatarCharacter,
    HeyGenColorBackground,
    HeyGenCreateVideoRequest,
    HeyGenDimension,
    HeyGenVideoInputScene,
    HeyGenVoiceInput,
    ProviderVideoStatus,
)


def _client() -> AsyncHeyGenClient:
    return AsyncHeyGenClient(api_key="test-key-abc")


def _minimal_request() -> HeyGenCreateVideoRequest:
    return HeyGenCreateVideoRequest(
        video_inputs=(
            HeyGenVideoInputScene(
                character=HeyGenAvatarCharacter(avatar_id="Annie_expressive_public"),
                voice=HeyGenVoiceInput(
                    input_text="Hello world.",
                    voice_id="voice-123",
                ),
                background=HeyGenColorBackground(value="#1A1A2E"),
            ),
        ),
        dimension=HeyGenDimension(width=1280, height=720),
        caption=False,
    )


def _mock_response(status_code: int, body: dict) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.text = json.dumps(body)
    return mock


# ── Construction ──────────────────────────────────────────────────────────────


def test_client_rejects_empty_api_key():
    with pytest.raises(HeyGenConfigurationError, match="API key"):
        AsyncHeyGenClient(api_key="")


def test_client_rejects_whitespace_api_key():
    with pytest.raises(HeyGenConfigurationError):
        AsyncHeyGenClient(api_key="   ")


def test_client_constructed_with_valid_key():
    client = _client()
    assert client is not None


def test_api_key_not_exposed_in_exception():
    client = _client()
    mock = _mock_response(401, {"error": "Unauthorized"})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenAuthenticationError) as exc_info:
            client._create_video_sync(_minimal_request())
    # API key must not appear in the exception message
    assert "test-key-abc" not in str(exc_info.value)


# ── create_video ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_video_success():
    client = _client()
    mock = _mock_response(200, {"data": {"video_id": "vid-xyz"}})
    with patch("httpx.post", return_value=mock):
        result = await client.create_video(_minimal_request())
    assert result.video_id == "vid-xyz"


@pytest.mark.asyncio
async def test_create_video_401_raises_authentication_error():
    client = _client()
    mock = _mock_response(401, {"error": "Unauthorized"})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenAuthenticationError):
            await client.create_video(_minimal_request())


@pytest.mark.asyncio
async def test_create_video_400_raises_invalid_request():
    client = _client()
    mock = _mock_response(400, {"error": {"code": "invalid_param"}})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenInvalidRequestError):
            await client.create_video(_minimal_request())


@pytest.mark.asyncio
async def test_create_video_429_raises_rate_limit():
    client = _client()
    mock = _mock_response(429, {"error": "too many requests"})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenRateLimitError):
            await client.create_video(_minimal_request())


@pytest.mark.asyncio
async def test_create_video_500_raises_transient():
    client = _client()
    mock = _mock_response(500, {"error": "server error"})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenTransientError):
            await client.create_video(_minimal_request())


@pytest.mark.asyncio
async def test_create_video_missing_video_id_raises_invalid_response():
    client = _client()
    mock = _mock_response(200, {"data": {}})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenInvalidResponseError):
            await client.create_video(_minimal_request())


@pytest.mark.asyncio
async def test_create_video_network_timeout_raises_transient():
    client = _client()
    with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
        with pytest.raises(HeyGenTransientError, match="timed out"):
            await client.create_video(_minimal_request())


# ── get_video_status ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_video_status_completed():
    client = _client()
    mock = _mock_response(200, {
        "data": {
            "status": "completed",
            "video_url": "https://cdn.heygen.com/test.mp4",
            "duration": 42.5,
        }
    })
    with patch("httpx.get", return_value=mock):
        result = await client.get_video_status("vid-xyz")
    assert result.status == ProviderVideoStatus.COMPLETED
    assert result.video_url == "https://cdn.heygen.com/test.mp4"
    assert result.duration == 42.5


@pytest.mark.asyncio
async def test_get_video_status_maps_v2_caption_url_to_subtitle_url():
    client = _client()
    mock = _mock_response(200, {
        "data": {
            "status": "completed",
            "video_url": "https://cdn.heygen.com/test.mp4",
            "caption_url": "https://cdn.heygen.com/test.srt",
        }
    })
    with patch("httpx.get", return_value=mock):
        result = await client.get_video_status("vid-captioned")
    assert result.subtitle_url == "https://cdn.heygen.com/test.srt"


@pytest.mark.asyncio
async def test_get_video_status_retains_legacy_subtitle_url_alias():
    client = _client()
    mock = _mock_response(200, {
        "data": {
            "status": "completed",
            "video_url": "https://cdn.heygen.com/test.mp4",
            "subtitle_url": "https://cdn.heygen.com/legacy.srt",
        }
    })
    with patch("httpx.get", return_value=mock):
        result = await client.get_video_status("vid-captioned")
    assert result.subtitle_url == "https://cdn.heygen.com/legacy.srt"


@pytest.mark.asyncio
async def test_get_video_status_failed():
    client = _client()
    mock = _mock_response(200, {
        "data": {"status": "failed", "error": "render_error"}
    })
    with patch("httpx.get", return_value=mock):
        result = await client.get_video_status("vid-fail")
    assert result.status == ProviderVideoStatus.FAILED
    assert result.error == "render_error"


@pytest.mark.asyncio
async def test_get_video_status_processing():
    client = _client()
    mock = _mock_response(200, {"data": {"status": "processing"}})
    with patch("httpx.get", return_value=mock):
        result = await client.get_video_status("vid-proc")
    assert result.status == ProviderVideoStatus.PROCESSING


@pytest.mark.asyncio
async def test_get_video_status_unknown_mapped_to_unknown():
    client = _client()
    mock = _mock_response(200, {"data": {"status": "exotic_new_status"}})
    with patch("httpx.get", return_value=mock):
        result = await client.get_video_status("vid-xyz")
    assert result.status == ProviderVideoStatus.UNKNOWN


# ── upload_asset ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_asset_success():
    client = _client()
    mock = _mock_response(200, {"data": {"asset_id": "asset-abc"}})
    with patch("httpx.post", return_value=mock):
        result = await client.upload_asset(
            filename="bg.png",
            data=b"fake_png_bytes",
            media_type="image/png",
        )
    assert result.asset_id == "asset-abc"


@pytest.mark.asyncio
async def test_upload_asset_missing_asset_id_raises_invalid_response():
    client = _client()
    mock = _mock_response(200, {"data": {}})
    with patch("httpx.post", return_value=mock):
        with pytest.raises(HeyGenInvalidResponseError):
            await client.upload_asset(filename="bg.png", data=b"x", media_type="image/png")


# ── download_bytes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_bytes_success():
    client = _client()
    mock = MagicMock()
    mock.content = b"fake_mp4_data"
    mock.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=mock):
        data = await client.download_bytes("https://cdn.heygen.com/test.mp4")
    assert data == b"fake_mp4_data"


@pytest.mark.asyncio
async def test_download_bytes_http_error_raises_download_error():
    client = _client()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    http_error = httpx.HTTPStatusError(
        message="403 Forbidden",
        request=MagicMock(),
        response=mock_resp,
    )
    mock_resp.raise_for_status.side_effect = http_error
    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(HeyGenDownloadError):
            await client.download_bytes("https://cdn.heygen.com/test.mp4")


# ── Wire format serialisation ─────────────────────────────────────────────────


def test_serialise_create_request_structure():
    req = _minimal_request()
    payload = _serialise_create_request(req)
    assert "video_inputs" in payload
    assert len(payload["video_inputs"]) == 1
    scene = payload["video_inputs"][0]
    assert scene["character"]["type"] == "avatar"
    assert scene["voice"]["input_text"] == "Hello world."
    assert scene["background"]["type"] == "color"
    assert payload["dimension"] == {"width": 1280, "height": 720}
    assert payload["caption"] is False


def test_serialise_image_background():
    from learning_pipeline.providers.heygen.models import HeyGenImageBackground

    req = HeyGenCreateVideoRequest(
        video_inputs=(
            HeyGenVideoInputScene(
                character=HeyGenAvatarCharacter(avatar_id="Annie_expressive_public"),
                voice=HeyGenVoiceInput(input_text="Hi.", voice_id="v-1"),
                background=HeyGenImageBackground(image_asset_id="asset-123"),
            ),
        ),
        dimension=HeyGenDimension(width=1280, height=720),
    )
    payload = _serialise_create_request(req)
    bg = payload["video_inputs"][0]["background"]
    assert bg["type"] == "image"
    assert bg["image_asset_id"] == "asset-123"
