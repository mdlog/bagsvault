"""Tests for the /api/health endpoint."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import get_db
from app.routers import health as health_router


def _make_app(db_override) -> FastAPI:
    app = FastAPI()
    app.include_router(health_router.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db_override
    return app


@pytest.mark.asyncio
async def test_health_ok(fake_db) -> None:
    app = _make_app(fake_db)
    transport = ASGITransport(app=app)
    with respx.mock(assert_all_called=False) as router:
        router.post(settings.solana_rpc_url).respond(
            200, json={"jsonrpc": "2.0", "id": 1, "result": "ok"}
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["mongo"]["status"] == "up"
    assert body["checks"]["solana_rpc"]["status"] == "up"


@pytest.mark.asyncio
async def test_health_degraded_when_rpc_unreachable(fake_db) -> None:
    app = _make_app(fake_db)
    transport = ASGITransport(app=app)
    with respx.mock() as router:
        router.post(settings.solana_rpc_url).mock(side_effect=httpx.ConnectError("boom"))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["solana_rpc"]["status"] == "down"


@pytest.mark.asyncio
async def test_health_degraded_when_mongo_down(fake_db) -> None:
    fake_db.command.side_effect = RuntimeError("no mongo")
    app = _make_app(fake_db)
    transport = ASGITransport(app=app)
    with respx.mock() as router:
        router.post(settings.solana_rpc_url).respond(
            200, json={"jsonrpc": "2.0", "id": 1, "result": "ok"}
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["mongo"]["status"] == "down"
