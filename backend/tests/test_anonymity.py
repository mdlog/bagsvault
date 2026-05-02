"""Tests for the anonymity-set + Merkle-root endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.exceptions import register_exception_handlers
from app.models.merkle import MerkleRoot
from app.routers import anonymity as anonymity_router
from app.services.deposit_service import DepositService
from app.services.merkle_indexer import MerkleIndexer


def _make_indexer(
    *,
    current: MerkleRoot | None = None,
    recent: list[MerkleRoot] | None = None,
) -> MagicMock:
    indexer = MagicMock(spec=MerkleIndexer)
    indexer.get_current_root = AsyncMock(return_value=current)
    indexer.get_recent_roots = AsyncMock(return_value=recent or [])
    indexer.sync_now = AsyncMock(return_value=None)
    return indexer


def _make_db(*, count: int = 0) -> MagicMock:
    db = MagicMock(name="db")
    db.commitments = MagicMock(name="commitments")
    db.commitments.count_documents = AsyncMock(return_value=count)
    return db


def _make_app(service: DepositService, indexer: MerkleIndexer) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(anonymity_router.router, prefix="/api")
    app.dependency_overrides[anonymity_router._make_deposit_service] = lambda: service
    app.dependency_overrides[anonymity_router._make_indexer] = lambda: indexer
    return app


@pytest.mark.asyncio
async def test_anonymity_set_returns_count_with_fallback_root() -> None:
    db = _make_db(count=128)
    indexer = _make_indexer(current=None)
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)  # type: ignore[arg-type]
    app = _make_app(service, indexer)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/anonymity-set")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 128
    assert body["current_root"] == "0" * 64
    assert body["source"] == "fallback"


@pytest.mark.asyncio
async def test_anonymity_set_uses_indexed_root_when_present() -> None:
    db = _make_db(count=5)
    root = MerkleRoot(
        root="ab" * 32,
        commitment_count=5,
        block_height=10,
        indexed_at=datetime.now(timezone.utc),
        source="indexed",
    )
    indexer = _make_indexer(current=root)
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)  # type: ignore[arg-type]
    app = _make_app(service, indexer)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/anonymity-set")
    body = resp.json()
    assert body["current_root"] == "ab" * 32
    assert body["source"] == "indexed"


@pytest.mark.asyncio
async def test_merkle_root_returns_fallback_when_cache_empty() -> None:
    db = _make_db()
    indexer = _make_indexer(recent=[])
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)  # type: ignore[arg-type]
    app = _make_app(service, indexer)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/merkle/root")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current"] == "0" * 64
    assert body["recent"] == []
    assert body["source"] == "fallback"
    assert "program_id" in body


@pytest.mark.asyncio
async def test_merkle_root_returns_cached_recent_list() -> None:
    db = _make_db()
    roots = [
        MerkleRoot(
            root="aa" * 32,
            commitment_count=2,
            block_height=20,
            indexed_at=datetime.now(timezone.utc),
            source="indexed",
        ),
        MerkleRoot(
            root="bb" * 32,
            commitment_count=1,
            block_height=10,
            indexed_at=datetime.now(timezone.utc),
            source="indexed",
        ),
    ]
    indexer = _make_indexer(recent=roots)
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)  # type: ignore[arg-type]
    app = _make_app(service, indexer)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/merkle/root")
    body = resp.json()
    assert body["current"] == "aa" * 32
    assert body["recent"] == ["aa" * 32, "bb" * 32]
    assert body["source"] == "indexed"
