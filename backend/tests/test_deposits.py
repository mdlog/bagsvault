"""Tests for the deposit service + router."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import base58
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nacl.signing import SigningKey

from app.auth import build_auth_message
from app.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)
from app.models.commitment import Commitment
from app.routers import deposits as deposits_router
from app.services.deposit_service import DepositService


def _make_db() -> MagicMock:
    db = MagicMock(name="db")
    db.commitments = MagicMock(name="commitments")
    db.commitments.find_one = AsyncMock(return_value=None)
    db.commitments.insert_one = AsyncMock()
    db.commitments.count_documents = AsyncMock(return_value=0)

    class _Cursor:
        def __init__(self, items: list[dict]) -> None:
            self._items = list(items)

        def sort(self, *_a, **_kw):  # noqa: ANN001, ANN003, ANN202
            return self

        def limit(self, *_a, **_kw):  # noqa: ANN001, ANN003, ANN202
            return self

        def __aiter__(self):  # noqa: ANN204
            return self

        async def __anext__(self) -> dict:
            if not self._items:
                raise StopAsyncIteration
            return self._items.pop(0)

    db.commitments.find = MagicMock(return_value=_Cursor([]))
    db.merkle_roots = MagicMock(name="merkle_roots")
    db.merkle_roots.find_one = AsyncMock(return_value=None)
    return db


def _make_indexer() -> MagicMock:
    indexer = MagicMock(name="indexer")
    indexer.sync_now = AsyncMock(return_value=None)
    indexer.get_recent_roots = AsyncMock(return_value=[])
    indexer.get_current_root = AsyncMock(return_value=None)
    return indexer


def _make_rpc(tx_result: Any) -> MagicMock:
    rpc = MagicMock(name="rpc")
    rpc.get_transaction = AsyncMock(return_value=tx_result)
    return rpc


# ----------------------------------------------------------------------
# Service-level
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_register_inserts_new_commitment() -> None:
    db = _make_db()
    indexer = _make_indexer()
    rpc = _make_rpc({"meta": {"err": None}})
    service = DepositService(rpc=rpc, db=db, merkle=indexer)

    record = await service.register(
        commitment="cafe" * 16,
        amount=1_000_000_000,
        token="SOL",
        tx_signature="SigAbc",
        creator_wallet=None,
    )

    assert isinstance(record, Commitment)
    assert record.merkle_index == 0
    db.commitments.insert_one.assert_awaited_once()
    indexer.sync_now.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_is_idempotent_on_same_signature() -> None:
    cached = {
        "id": "abc",
        "commitment": "ff" * 32,
        "merkle_index": 0,
        "amount": 1,
        "token": "SOL",
        "tx_signature": "SigSame",
        "creator_wallet": None,
        "created_at": datetime.now(timezone.utc),
    }
    db = _make_db()
    db.commitments.find_one.return_value = cached
    rpc = _make_rpc({"meta": {"err": None}})
    indexer = _make_indexer()
    service = DepositService(rpc=rpc, db=db, merkle=indexer)

    record = await service.register(
        commitment="ff" * 32,
        amount=1,
        token="SOL",
        tx_signature="SigSame",
        creator_wallet=None,
    )

    assert record.tx_signature == "SigSame"
    rpc.get_transaction.assert_not_called()
    db.commitments.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_register_conflict_on_different_signature() -> None:
    cached = {
        "id": "abc",
        "commitment": "ff" * 32,
        "merkle_index": 0,
        "amount": 1,
        "token": "SOL",
        "tx_signature": "SigA",
        "creator_wallet": None,
        "created_at": datetime.now(timezone.utc),
    }
    db = _make_db()
    db.commitments.find_one.return_value = cached
    rpc = _make_rpc({"meta": {"err": None}})
    indexer = _make_indexer()
    service = DepositService(rpc=rpc, db=db, merkle=indexer)

    with pytest.raises(ConflictError):
        await service.register(
            commitment="ff" * 32,
            amount=1,
            token="SOL",
            tx_signature="SigB",
            creator_wallet=None,
        )


@pytest.mark.asyncio
async def test_register_404_when_tx_missing() -> None:
    db = _make_db()
    rpc = _make_rpc(None)
    indexer = _make_indexer()
    service = DepositService(rpc=rpc, db=db, merkle=indexer)

    with pytest.raises(NotFoundError):
        await service.register(
            commitment="aa" * 32,
            amount=1,
            token="SOL",
            tx_signature="SigGhost",
            creator_wallet=None,
        )


@pytest.mark.asyncio
async def test_register_400_when_tx_failed() -> None:
    db = _make_db()
    rpc = _make_rpc({"meta": {"err": {"InstructionError": [0, "Custom"]}}})
    indexer = _make_indexer()
    service = DepositService(rpc=rpc, db=db, merkle=indexer)

    with pytest.raises(ValidationError):
        await service.register(
            commitment="aa" * 32,
            amount=1,
            token="SOL",
            tx_signature="SigBad",
            creator_wallet=None,
        )


@pytest.mark.asyncio
async def test_register_continues_when_indexer_fails() -> None:
    db = _make_db()
    rpc = _make_rpc({"meta": {"err": None}})
    indexer = _make_indexer()
    indexer.sync_now.side_effect = RuntimeError("indexer down")
    service = DepositService(rpc=rpc, db=db, merkle=indexer)

    record = await service.register(
        commitment="bb" * 32,
        amount=1,
        token="SOL",
        tx_signature="SigOk",
        creator_wallet=None,
    )
    assert record is not None


@pytest.mark.asyncio
async def test_list_recent_anonymizes_records() -> None:
    db = _make_db()
    items = [
        {
            "commitment": "abcd" + "0" * 56 + "1234",
            "amount": 1_000_000,
            "token": "SOL",
            "merkle_index": 0,
            "tx_signature": "SECRET",
            "creator_wallet": "SECRET-WALLET",
            "created_at": datetime.now(timezone.utc),
        }
    ]

    class _Cursor:
        def __init__(self, items: list[dict]) -> None:
            self._items = list(items)

        def sort(self, *_a, **_kw):  # noqa: ANN001, ANN003, ANN202
            return self

        def limit(self, *_a, **_kw):  # noqa: ANN001, ANN003, ANN202
            return self

        def __aiter__(self):  # noqa: ANN204
            return self

        async def __anext__(self) -> dict:
            if not self._items:
                raise StopAsyncIteration
            return self._items.pop(0)

    db.commitments.find = MagicMock(return_value=_Cursor(items))
    indexer = _make_indexer()
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)

    out = await service.list_recent()

    assert len(out) == 1
    entry = out[0]
    assert "creator_wallet" not in entry
    assert "tx_signature" not in entry
    assert entry["commitment_hash_short"].startswith("abcd")
    assert entry["commitment_hash_short"].endswith("1234")
    assert "…" in entry["commitment_hash_short"]


@pytest.mark.asyncio
async def test_get_anonymity_set_falls_back_when_no_root() -> None:
    db = _make_db()
    db.commitments.count_documents = AsyncMock(return_value=42)
    indexer = _make_indexer()
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)

    out = await service.get_anonymity_set()

    assert out["count"] == 42
    assert out["current_root"] == "0" * 64
    assert out["source"] == "fallback"


# ----------------------------------------------------------------------
# Router-level (end-to-end)
# ----------------------------------------------------------------------
def _make_app(service: DepositService) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(deposits_router.router, prefix="/api")
    app.dependency_overrides[deposits_router.get_deposit_service] = lambda: service
    return app


def _signed_headers() -> tuple[dict[str, str], str]:
    sk = SigningKey.generate()
    address = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    issued_at = datetime.now(timezone.utc)
    message = build_auth_message("bagsvault.app", address, "nonce-1", issued_at)
    sig_b58 = base58.b58encode(sk.sign(message.encode("utf-8")).signature).decode("ascii")
    return (
        {
            "X-Wallet-Address": address,
            "X-Wallet-Signature": sig_b58,
            "X-Wallet-Message": message,
        },
        address,
    )


@pytest.mark.asyncio
async def test_router_post_deposit_requires_wallet_headers() -> None:
    db = _make_db()
    indexer = _make_indexer()
    rpc = _make_rpc({"meta": {"err": None}})
    service = DepositService(rpc=rpc, db=db, merkle=indexer)
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/deposits",
            json={
                "commitment": "aa" * 32,
                "amount": 1,
                "token": "SOL",
                "tx_signature": "SigOk",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_router_post_deposit_happy_path() -> None:
    db = _make_db()
    indexer = _make_indexer()
    rpc = _make_rpc({"meta": {"err": None}})
    service = DepositService(rpc=rpc, db=db, merkle=indexer)
    app = _make_app(service)
    headers, _addr = _signed_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/deposits",
            json={
                "commitment": "aa" * 32,
                "amount": 1_000_000,
                "token": "SOL",
                "tx_signature": "SigOk",
            },
            headers=headers,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["commitment"] == "aa" * 32
    assert body["merkle_index"] == 0


@pytest.mark.asyncio
async def test_router_get_recent_anonymized() -> None:
    db = _make_db()
    indexer = _make_indexer()
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/deposits/recent?limit=10")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_router_get_recent_limit_validation() -> None:
    db = _make_db()
    indexer = _make_indexer()
    service = DepositService(rpc=MagicMock(), db=db, merkle=indexer)
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/deposits/recent?limit=500")
    assert resp.status_code == 422
