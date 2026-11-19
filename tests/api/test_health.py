"""GET /health/live and /health/ready — health endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_live_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_ready_without_database_returns_503(client: AsyncClient) -> None:
    # The test client uses create_app() with no DATABASE_URL set,
    # so app.state.pool is None and /health/ready must return 503.
    response = await client.get("/health/ready")
    assert response.status_code == 503
