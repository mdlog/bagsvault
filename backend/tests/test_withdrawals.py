"""Tests for the withdrawal service + ``/api/withdrawals`` router."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from solders.keypair import Keypair

from app.clients.solana_signer import SolanaSignerClient
from app.config import settings
from app.exceptions import ConflictError, ServiceUnavailableError, register_exception_handlers
from app.models.withdrawal import WithdrawalPublicInputs, WithdrawalRelayRequest
from app.routers import withdrawals as withdrawals_router
from app.services.relayer_service import RelayerService
from app.services.withdrawal_service import WithdrawalService


# ----------------------------------------------------------------------
# Fixtures and fakes
# ----------------------------------------------------------------------
class _FakeRpc:
    """Stub that mimics ``app.clients.solana_rpc.SolanaRpcClient``."""

    def __init__(
        self,
        *,
        blockhash: Any = None,
        signature: str = "5sigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsigsig",  # noqa: E501
        raise_on_send: Exception | None = None,
    ) -> None:
        self.blockhash = blockhash or {
            "blockhash": "11111111111111111111111111111111",
            "lastValidBlockHeight": 1,
        }
        self.signature = signature
        self.raise_on_send = raise_on_send
        self.sent: list[tuple[str, bool]] = []

    async def get_recent_blockhash(self) -> Any:
        return self.blockhash

    async def send_transaction(self, signed_tx_b64: str, skip_preflight: bool = False) -> str:
        self.sent.append((signed_tx_b64, skip_preflight))
        if self.raise_on_send is not None:
            raise self.raise_on_send
        return self.signature

    async def get_transaction(self, sig: str) -> dict[str, Any] | None:
        return None


class _FakeFindCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)

    def sort(self, *args: Any, **kwargs: Any) -> "_FakeFindCursor":
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


def _make_db(
    *,
    nullifier_already_spent: bool = False,
    relayers: list[dict[str, Any]] | None = None,
    withdrawals: list[dict[str, Any]] | None = None,
) -> MagicMock:
    relayer_storage: list[dict[str, Any]] = list(relayers or [])
    withdrawal_storage: list[dict[str, Any]] = list(withdrawals or [])

    db = MagicMock(name="db")
    db.relayers = MagicMock(name="relayers")
    db.withdrawals = MagicMock(name="withdrawals")

    async def withdrawals_find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        if nullifier_already_spent and "nullifier_hash" in query:
            return {"nullifier_hash": query["nullifier_hash"], "tx_signature": "old"}
        for doc in withdrawal_storage:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def withdrawals_insert_one(doc: dict[str, Any]) -> MagicMock:
        withdrawal_storage.append(dict(doc))
        return MagicMock(inserted_id="x")

    def withdrawals_find(*args: Any, **kwargs: Any) -> _FakeFindCursor:
        return _FakeFindCursor(list(withdrawal_storage))

    db.withdrawals.find_one = AsyncMock(side_effect=withdrawals_find_one)
    db.withdrawals.insert_one = AsyncMock(side_effect=withdrawals_insert_one)
    db.withdrawals.find = MagicMock(side_effect=withdrawals_find)

    async def relayers_find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in relayer_storage:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def relayers_find(*args: Any, **kwargs: Any) -> _FakeFindCursor:
        return _FakeFindCursor(list(relayer_storage))

    async def relayers_update_one(*args: Any, **kwargs: Any) -> MagicMock:
        return MagicMock()

    db.relayers.find_one = AsyncMock(side_effect=relayers_find_one)
    db.relayers.find = MagicMock(side_effect=relayers_find)
    db.relayers.update_one = AsyncMock(side_effect=relayers_update_one)

    return db


def _relayer_doc(relayer_id: str = "rly-self", name: str = "Self") -> dict[str, Any]:
    return {
        "id": f"uuid-{relayer_id}",
        "relayer_id": relayer_id,
        "name": name,
        "operator": f"{relayer_id}.sol",
        "pubkey": f"pubkey-{relayer_id}",
        "region": "US-East",
        "fee_bps": 15,
        "ping_ms": 42,
        "uptime_pct": 99.9,
        "jobs_24h": 0,
        "volume_24h_lamports": 0,
        "last_seen": None,
        "registered_at": datetime(2024, 5, 1, tzinfo=timezone.utc),
    }


@pytest.fixture
def signer(tmp_path: Path) -> SolanaSignerClient:
    kp = Keypair()
    path = tmp_path / "relayer.json"
    path.write_text(json.dumps(list(bytes(kp))))
    return SolanaSignerClient(keypair_path=path)


def _relay_request(
    *,
    nullifier_hash: str = "deadbeef" * 8,
    amount: int = 1_000_000_000,
) -> WithdrawalRelayRequest:
    return WithdrawalRelayRequest(
        proof="aa" * 32,
        public_inputs=WithdrawalPublicInputs(
            root="ab" * 32,
            nullifier_hash=nullifier_hash,
            recipient="11111111111111111111111111111111",
            amount=amount,
            token="SOL",
        ),
    )


# Some tests need a valid base58 program/verifier id. "11111111111111111111111111111111"
# is the System Program — guaranteed to parse as a valid Pubkey on every cluster.
SYSTEM_PROGRAM = "11111111111111111111111111111111"


# ----------------------------------------------------------------------
# Service-level
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_relay_rejects_double_spend(signer: SolanaSignerClient) -> None:
    db = _make_db(nullifier_already_spent=True, relayers=[_relayer_doc()])
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    with pytest.raises(ConflictError) as ei:
        await service.relay(_relay_request())
    assert "Nullifier already spent" in ei.value.message
    assert rpc.sent == []


@pytest.mark.asyncio
async def test_relay_503_when_program_id_empty(
    monkeypatch: pytest.MonkeyPatch, signer: SolanaSignerClient
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", "")
    db = _make_db(relayers=[_relayer_doc()])
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    with pytest.raises(ServiceUnavailableError) as ei:
        await service.relay(_relay_request())
    assert ei.value.details["missing_env"] == "BAGSVAULT_PROGRAM_ID"


@pytest.mark.asyncio
async def test_relay_503_when_no_relayers(
    monkeypatch: pytest.MonkeyPatch, signer: SolanaSignerClient
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", SYSTEM_PROGRAM)
    monkeypatch.setattr(settings, "bagsvault_verifier_id", SYSTEM_PROGRAM)
    db = _make_db(relayers=[])  # empty registry
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    with pytest.raises(ServiceUnavailableError) as ei:
        await service.relay(_relay_request())
    assert "No relayers registered" in ei.value.message


@pytest.mark.asyncio
async def test_relay_happy_path_persists_and_returns_signature(
    monkeypatch: pytest.MonkeyPatch, signer: SolanaSignerClient
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", SYSTEM_PROGRAM)
    monkeypatch.setattr(settings, "bagsvault_verifier_id", SYSTEM_PROGRAM)

    db = _make_db(relayers=[_relayer_doc()])
    rpc = _FakeRpc(signature="abc123sig")
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)

    out = await service.relay(_relay_request())
    assert out["signature"] == "abc123sig"
    assert out["status"] == "submitted"

    # Sent the transaction once.
    assert len(rpc.sent) == 1
    sent_b64, skip_preflight = rpc.sent[0]
    assert isinstance(sent_b64, str) and sent_b64
    assert skip_preflight is False

    # Persisted the withdrawal row.
    db.withdrawals.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_relay_accepts_blockhash_dict_and_str(
    monkeypatch: pytest.MonkeyPatch, signer: SolanaSignerClient
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", SYSTEM_PROGRAM)
    monkeypatch.setattr(settings, "bagsvault_verifier_id", SYSTEM_PROGRAM)

    db = _make_db(relayers=[_relayer_doc()])
    # Simulate the Agent A dict envelope.
    rpc = _FakeRpc(
        blockhash={"blockhash": "11111111111111111111111111111111", "lastValidBlockHeight": 7}
    )
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    out = await service.relay(_relay_request())
    assert out["status"] == "submitted"


@pytest.mark.asyncio
async def test_list_recent_anonymizes_recipient_and_uses_relayer_name(
    signer: SolanaSignerClient,
) -> None:
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    db = _make_db(
        relayers=[_relayer_doc("rly-1", name="NovaRelay")],
        withdrawals=[
            {
                "id": "w1",
                "nullifier_hash": "n" * 64,
                "recipient": "secret-recipient-do-not-leak",
                "amount": 1_000_000_000,
                "token": "SOL",
                "relayer_id": "rly-1",
                "tx_signature": "5a2f1234567890aaaa9c1b",
                "created_at": now,
            }
        ],
    )
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    items = await service.list_recent()
    assert len(items) == 1
    item = items[0]
    assert "recipient" not in item  # anonymized
    assert item["hash"] == "5a2f…9c1b"
    assert item["relayer_name"] == "NovaRelay"
    assert item["token"] == "SOL"
    assert item["amount"] == 1_000_000_000
    assert item["relative_time"].endswith("ago")


# ----------------------------------------------------------------------
# Router-level
# ----------------------------------------------------------------------
def _make_app(service: WithdrawalService) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(withdrawals_router.router, prefix="/api")
    app.dependency_overrides[withdrawals_router.get_withdrawal_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_router_relay_double_spend_returns_409(signer: SolanaSignerClient) -> None:
    db = _make_db(nullifier_already_spent=True, relayers=[_relayer_doc()])
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    app = _make_app(service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/withdrawals/relay",
            json={
                "proof": "aa" * 32,
                "public_inputs": {
                    "root": "ab" * 32,
                    "nullifier_hash": "deadbeef" * 8,
                    "recipient": "11111111111111111111111111111111",
                    "amount": 1_000_000_000,
                    "token": "SOL",
                },
            },
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_router_relay_program_unconfigured_returns_503(
    monkeypatch: pytest.MonkeyPatch, signer: SolanaSignerClient
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", "")
    db = _make_db(relayers=[_relayer_doc()])
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    app = _make_app(service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/withdrawals/relay",
            json={
                "proof": "aa" * 32,
                "public_inputs": {
                    "root": "ab" * 32,
                    "nullifier_hash": "11" * 32,
                    "recipient": "11111111111111111111111111111111",
                    "amount": 1_000_000_000,
                    "token": "SOL",
                },
            },
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_router_relay_no_relayers_returns_503(
    monkeypatch: pytest.MonkeyPatch, signer: SolanaSignerClient
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", SYSTEM_PROGRAM)
    monkeypatch.setattr(settings, "bagsvault_verifier_id", SYSTEM_PROGRAM)
    db = _make_db(relayers=[])
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    app = _make_app(service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/withdrawals/relay",
            json={
                "proof": "aa" * 32,
                "public_inputs": {
                    "root": "ab" * 32,
                    "nullifier_hash": "22" * 32,
                    "recipient": "11111111111111111111111111111111",
                    "amount": 1_000_000_000,
                    "token": "SOL",
                },
            },
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_router_recent_returns_anonymized_list(signer: SolanaSignerClient) -> None:
    now = datetime.now(timezone.utc) - timedelta(minutes=4)
    db = _make_db(
        relayers=[_relayer_doc("rly-1", name="NovaRelay")],
        withdrawals=[
            {
                "id": "w1",
                "nullifier_hash": "n" * 64,
                "recipient": "leak",
                "amount": 10,
                "token": "SOL",
                "relayer_id": "rly-1",
                "tx_signature": "abcd1234efgh5678",
                "created_at": now,
            }
        ],
    )
    rpc = _FakeRpc()
    relayers = RelayerService(db=db)
    service = WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)
    app = _make_app(service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/withdrawals/recent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert "recipient" not in item
    assert item["relayer_name"] == "NovaRelay"
    assert item["hash"] == "abcd…5678"
