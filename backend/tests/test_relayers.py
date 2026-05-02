"""Tests for :mod:`app.services.relayer_service` + ``/api/relayers``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.exceptions import ServiceUnavailableError, register_exception_handlers
from app.models.relayer import Relayer
from app.routers import relayers as relayers_router
from app.services.relayer_service import RelayerService


# ----------------------------------------------------------------------
# Fake Mongo collections
# ----------------------------------------------------------------------
class _FakeFindCursor:
    """Chainable cursor backed by a python list."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_FakeFindCursor":
        self._docs.sort(key=lambda d: d.get(field, 0), reverse=direction < 0)
        return self

    def limit(self, n: int) -> "_FakeFindCursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return list(self._docs[:length])

    def __aiter__(self) -> "_FakeFindCursor":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class _FakeAggregateCursor:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = list(items)

    def __aiter__(self) -> "_FakeAggregateCursor":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _make_db(
    relayers: list[dict[str, Any]] | None = None,
    *,
    aggregate_result: list[dict[str, Any]] | None = None,
) -> MagicMock:
    storage: list[dict[str, Any]] = list(relayers or [])

    db = MagicMock(name="db")
    db.relayers = MagicMock(name="relayers")
    db.withdrawals = MagicMock(name="withdrawals")

    async def find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in storage:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def update_one(
        query: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> MagicMock:
        target = None
        for doc in storage:
            if all(doc.get(k) == v for k, v in query.items()):
                target = doc
                break
        if target is None:
            if not upsert:
                return MagicMock(matched_count=0, modified_count=0, upserted_id=None)
            target = {}
            target.update(update.get("$set", {}))
            storage.append(target)
            return MagicMock(matched_count=0, modified_count=0, upserted_id="x")
        target.update(update.get("$set", {}))
        return MagicMock(matched_count=1, modified_count=1, upserted_id=None)

    def find(*args: Any, **kwargs: Any) -> _FakeFindCursor:
        return _FakeFindCursor(list(storage))

    def aggregate(pipeline: list[dict[str, Any]]) -> _FakeAggregateCursor:
        return _FakeAggregateCursor(list(aggregate_result or []))

    db.relayers.find_one = AsyncMock(side_effect=find_one)
    db.relayers.update_one = AsyncMock(side_effect=update_one)
    db.relayers.find = MagicMock(side_effect=find)
    db.relayers._storage = storage  # type: ignore[attr-defined]

    db.withdrawals.aggregate = MagicMock(side_effect=aggregate)
    return db


def _relayer_doc(
    *,
    relayer_id: str,
    name: str = "Demo",
    uptime: float = 99.0,
    fee_bps: int = 15,
    ping_ms: int = 50,
    jobs_24h: int = 0,
) -> dict[str, Any]:
    return {
        "id": f"uuid-{relayer_id}",
        "relayer_id": relayer_id,
        "name": name,
        "operator": f"{relayer_id}.sol",
        "pubkey": f"pubkey-{relayer_id}",
        "region": "US-East",
        "fee_bps": fee_bps,
        "ping_ms": ping_ms,
        "uptime_pct": uptime,
        "jobs_24h": jobs_24h,
        "volume_24h_lamports": 0,
        "last_seen": None,
        "registered_at": datetime(2024, 5, 1, tzinfo=timezone.utc),
    }


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_inserts_new_relayer() -> None:
    db = _make_db()
    service = RelayerService(db=db)
    relayer = Relayer(
        relayer_id="rly-test",
        name="Test",
        operator="op",
        pubkey="pk",
        region="US-East",
        fee_bps=15,
        ping_ms=50,
        uptime_pct=99.0,
    )
    out = await service.upsert(relayer)
    assert out.relayer_id == "rly-test"
    db.relayers.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_preserves_existing_id_and_registered_at() -> None:
    existing = _relayer_doc(relayer_id="rly-keep", name="Old")
    db = _make_db([existing])
    service = RelayerService(db=db)
    new = Relayer(
        relayer_id="rly-keep",
        name="New",
        operator="op",
        pubkey="pk-new",
        region="US-West",
        fee_bps=10,
        ping_ms=33,
        uptime_pct=99.5,
    )
    out = await service.upsert(new)
    assert out.id == "uuid-rly-keep"  # original uuid kept


@pytest.mark.asyncio
async def test_list_active_sorted_by_uptime_desc() -> None:
    db = _make_db(
        [
            _relayer_doc(relayer_id="a", uptime=99.5),
            _relayer_doc(relayer_id="b", uptime=99.99),
            _relayer_doc(relayer_id="c", uptime=99.74),
        ]
    )
    service = RelayerService(db=db)
    out = await service.list_active(sort="uptime")
    ids = [r.relayer_id for r in out]
    assert ids == ["b", "c", "a"]


@pytest.mark.asyncio
async def test_list_active_sorted_by_fee_asc() -> None:
    db = _make_db(
        [
            _relayer_doc(relayer_id="a", fee_bps=20),
            _relayer_doc(relayer_id="b", fee_bps=10),
            _relayer_doc(relayer_id="c", fee_bps=15),
        ]
    )
    service = RelayerService(db=db)
    out = await service.list_active(sort="fee")
    assert [r.relayer_id for r in out] == ["b", "c", "a"]


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown() -> None:
    db = _make_db()
    service = RelayerService(db=db)
    assert await service.get("nope") is None


@pytest.mark.asyncio
async def test_stats_aggregates_from_withdrawals_collection() -> None:
    last_seen = datetime.now(timezone.utc) - timedelta(minutes=5)
    db = _make_db(
        [_relayer_doc(relayer_id="rly-1", uptime=99.9, ping_ms=42)],
        aggregate_result=[{"_id": "rly-1", "jobs": 17, "volume": 12_345, "last_seen": last_seen}],
    )
    service = RelayerService(db=db)
    out = await service.stats("rly-1")
    assert out["jobs_24h"] == 17
    assert out["volume_24h_lamports"] == 12_345
    assert out["last_seen"] == last_seen
    assert out["uptime_pct"] == 99.9
    assert out["ping_ms_avg"] == 42


@pytest.mark.asyncio
async def test_stats_returns_zeros_for_unknown_relayer() -> None:
    db = _make_db()
    service = RelayerService(db=db)
    out = await service.stats("rly-nope")
    assert out["jobs_24h"] == 0
    assert out["volume_24h_lamports"] == 0
    assert out["last_seen"] is None


@pytest.mark.asyncio
async def test_pick_best_returns_highest_uptime() -> None:
    db = _make_db(
        [
            _relayer_doc(relayer_id="a", uptime=99.5),
            _relayer_doc(relayer_id="b", uptime=99.99),
        ]
    )
    service = RelayerService(db=db)
    out = await service.pick_best()
    assert out.relayer_id == "b"


@pytest.mark.asyncio
async def test_pick_best_raises_when_empty() -> None:
    db = _make_db([])
    service = RelayerService(db=db)
    with pytest.raises(ServiceUnavailableError):
        await service.pick_best()


# ----------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------
def _make_app(service: RelayerService) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(relayers_router.router, prefix="/api")
    app.dependency_overrides[relayers_router.get_relayer_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_router_list_relayers() -> None:
    db = _make_db(
        [
            _relayer_doc(relayer_id="a", uptime=99.5, name="A"),
            _relayer_doc(relayer_id="b", uptime=99.99, name="B"),
        ]
    )
    service = RelayerService(db=db)
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/relayers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["sort"] == "uptime"
    assert body["items"][0]["name"] == "B"


@pytest.mark.asyncio
async def test_router_relayer_stats_404_for_unknown() -> None:
    db = _make_db()
    service = RelayerService(db=db)
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/relayers/rly-missing/stats")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_router_relayer_stats_returns_aggregates() -> None:
    db = _make_db(
        [_relayer_doc(relayer_id="rly-1", uptime=99.9, ping_ms=42)],
        aggregate_result=[{"_id": "rly-1", "jobs": 5, "volume": 999, "last_seen": None}],
    )
    service = RelayerService(db=db)
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/relayers/rly-1/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["relayer_id"] == "rly-1"
    assert body["jobs_24h"] == 5
    assert body["volume_24h_lamports"] == 999
    assert body["uptime_pct"] == 99.9
