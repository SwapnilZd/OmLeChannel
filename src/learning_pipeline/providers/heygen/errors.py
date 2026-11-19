"""Error classification for the HeyGen provider adapter.

Error categories and retry policy:
  HeyGenConfigurationError  — terminal; bad API key or missing required config
  HeyGenAuthenticationError — terminal; 401/403 from HeyGen
  HeyGenInvalidRequestError — terminal; 400 bad request (task-input failure)
  HeyGenRateLimitError      — retryable; 429
  HeyGenTransientError      — retryable; network timeout or 5xx
  HeyGenOperationFailedError— terminal for this submitted operation; provider render failed
  HeyGenOperationTimeoutError — polling timed out; preserves provider_video_id for resume
  HeyGenInvalidResponseError— retryable; unparseable response body
  HeyGenDownloadError       — retryable; failed to download completed video/subtitle
"""
from __future__ import annotations


class HeyGenError(Exception):
    """Base class for all HeyGen provider errors."""


class HeyGenConfigurationError(HeyGenError):
    """API key or required configuration is missing or invalid. Terminal."""


class HeyGenAuthenticationError(HeyGenError):
    """Authentication or authorization rejected by HeyGen. Terminal."""


class HeyGenInvalidRequestError(HeyGenError):
    """The request payload was rejected as invalid by HeyGen. Terminal."""


class HeyGenRateLimitError(HeyGenError):
    """HeyGen rate limit exceeded. Retryable."""


class HeyGenTransientError(HeyGenError):
    """Transient network or server error. Retryable."""


class HeyGenOperationFailedError(HeyGenError):
    """Provider render operation failed. Terminal for this submitted operation."""


class HeyGenOperationTimeoutError(HeyGenError):
    """Polling timed out without a terminal status.

    ``provider_video_id`` is preserved so a later retry can resume polling
    rather than submitting a new paid operation.
    """

    def __init__(self, message: str, *, provider_video_id: str) -> None:
        super().__init__(message)
        self.provider_video_id = provider_video_id


class HeyGenInvalidResponseError(HeyGenError):
    """HeyGen returned a response body that could not be parsed. Retryable."""


class HeyGenDownloadError(HeyGenError):
    """Downloading completed video or subtitle bytes failed. Retryable."""
