from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from src import app as app_module


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("POC_AUTH_ENABLED", "true")
    monkeypatch.setenv("POC_AUTH_PASSWORD", "omnichannel")
    monkeypatch.setenv("POC_AUTH_SECRET", "test-signing-secret")
    monkeypatch.setattr(
        app_module,
        "_templates",
        Jinja2Templates(directory=str(app_module.TEMPLATES_DIR)),
    )
    return TestClient(app_module.app)


def test_protected_ui_redirects_to_login(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/commission", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_deloitte_user_can_login_and_logout(monkeypatch):
    client = _client(monkeypatch)

    login = client.post(
        "/login",
        data={"email": "person@deloitte.com", "password": "omnichannel"},
        follow_redirects=False,
    )
    protected = client.get("/commission")
    jobs = client.get("/jobs")
    logout = client.get("/logout", follow_redirects=False)

    assert login.status_code == 303
    assert "omnichannel_session=" in login.headers["set-cookie"]
    assert "HttpOnly" in login.headers["set-cookie"]
    assert protected.status_code == 200
    assert jobs.status_code == 200
    assert logout.status_code == 303


def test_login_rejects_non_deloitte_email(monkeypatch):
    client = _client(monkeypatch)

    response = client.post(
        "/login",
        data={"email": "person@example.com", "password": "omnichannel"},
    )

    assert response.status_code == 401
    assert "Deloitte email address" in response.text


def test_integrated_pages_use_same_origin_commissioning_gateway():
    for template_name in ("commission.html", "jobs.html"):
        html = (app_module.TEMPLATES_DIR / template_name).read_text()

        assert "'/commissioning-api'" in html
        assert "localhost:8010" not in html

    commission_html = (app_module.TEMPLATES_DIR / "commission.html").read_text()
    assert "Catalog compatibility exclusions" in commission_html
    assert "preview.compatibility_errors" in commission_html
