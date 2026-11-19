from poc_auth import create_session, session_email, valid_credentials
import pytest
from httpx import ASGITransport, AsyncClient

from learning_commissioning.api.app import app as commissioning_app


def test_accepts_any_deloitte_email_with_shared_password(monkeypatch):
    monkeypatch.setenv("POC_AUTH_PASSWORD", "omnichannel")

    assert valid_credentials("person@deloitte.com", "omnichannel")
    assert valid_credentials("PERSON@DELOITTE.COM", "omnichannel")
    assert not valid_credentials("person@example.com", "omnichannel")
    assert not valid_credentials("@deloitte.com", "omnichannel")
    assert not valid_credentials("person@deloitte.com", "wrong")


def test_session_is_signed_and_expires(monkeypatch):
    monkeypatch.setenv("POC_AUTH_SECRET", "test-signing-secret")
    token = create_session("person@deloitte.com", now=100)

    assert session_email(token, now=101) == "person@deloitte.com"
    assert session_email(token + "tampered", now=101) is None
    assert session_email(token, now=100 + 12 * 60 * 60 + 1) is None


@pytest.mark.asyncio
async def test_commissioning_api_requires_session_when_enabled(monkeypatch):
    monkeypatch.setenv("POC_AUTH_ENABLED", "true")
    async with AsyncClient(
        transport=ASGITransport(app=commissioning_app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/commissioning-jobs")

    assert response.status_code == 401
