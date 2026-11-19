"""Minimal shared authentication for the internal POC UI."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time

from fastapi import HTTPException, Request

COOKIE_NAME = "omnichannel_session"
SESSION_SECONDS = 12 * 60 * 60


def auth_enabled() -> bool:
    return os.getenv("POC_AUTH_ENABLED", "false").strip().lower() == "true"


def valid_credentials(email: str, password: str) -> bool:
    normalized = email.strip().lower()
    local, separator, domain = normalized.rpartition("@")
    expected = os.getenv("POC_AUTH_PASSWORD", "omnichannel")
    return bool(local and separator and domain == "deloitte.com") and hmac.compare_digest(
        password, expected
    )


def create_session(email: str, *, now: int | None = None) -> str:
    issued_at = int(time.time()) if now is None else now
    payload = json.dumps(
        {"email": email.strip().lower(), "exp": issued_at + SESSION_SECONDS},
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(_secret(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def session_email(token: str | None, *, now: int | None = None) -> str | None:
    if not token:
        return None
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_secret(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        )
        current_time = int(time.time()) if now is None else now
        email = str(payload["email"])
        if int(payload["exp"]) < current_time or not email.endswith("@deloitte.com"):
            return None
        return email
    except (KeyError, TypeError, ValueError, binascii.Error, json.JSONDecodeError):
        return None


def request_email(request: Request) -> str | None:
    return session_email(request.cookies.get(COOKIE_NAME))


def require_authenticated_request(request: Request) -> str | None:
    if not auth_enabled():
        return None
    email = request_email(request)
    if email is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return email


def cookie_secure() -> bool:
    return os.getenv("POC_AUTH_COOKIE_SECURE", "false").strip().lower() == "true"


def _secret() -> bytes:
    return os.getenv("POC_AUTH_SECRET", "local-poc-auth-secret-change-me").encode()
