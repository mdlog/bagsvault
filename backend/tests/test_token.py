"""Tests for the token registry service + router."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.exceptions import ConflictError, NotFoundError, register_exception_handlers
from app.models.token import TokenRegister
from app.routers import tokens as tokens_router
from app.services.token_service import TokenService


# ----------------------------------------------------------------------
# Test fixtures
# ----------------------------------------------------------------------
class _FakeBagsClient:
    """In-memory stand-in for BagsAPIClient.get_token_metadata."""

    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.metadata = metadata
        self.calls = 0

    async def get_token_metadata(self, mint: str) -> dict[str, Any]:
        self.calls += 1
        if self.metadata is None:
            raise RuntimeError("metadata fetch boom")
        return self.metadata


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def skip(self, n: int) -> "_FakeCursor":
        return _FakeCursor(self._docs[n:])

    def limit(self, n: int) -> "_FakeCursor":
        return _FakeCursor(self._docs[:n])

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return list(self._docs[:length])


def _make_db(initial_tokens: list[dict[str, Any]] | None = None) -> MagicMock:
    """Build a fake AsyncIOMotorDatabase that backs db.tokens with a list."""

    storage: list[dict[str, Any]] = list(initial_tokens or [])

    db = MagicMock(name="db")
    db.tokens = MagicMock(name="tokens")

    async def find_one(query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in storage:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def insert_one(doc: dict[str, Any]) -> MagicMock:
        storage.append(dict(doc))
        result = MagicMock()
        result.inserted_id = doc.get("id", "fake-id")
        return result

    def find(*args: Any, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(list(storage))

    db.tokens.find_one = AsyncMock(side_effect=find_one)
    db.tokens.insert_one = AsyncMock(side_effect=insert_one)
    db.tokens.find = MagicMock(side_effect=find)
    db.tokens._storage = storage  # type: ignore[attr-defined]

    db.creators = MagicMock(name="creators")
    db.creators.update_one = AsyncMock()

    return db


# ----------------------------------------------------------------------
# Service: register
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_register_inserts_new_token() -> None:
    db = _make_db()
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    payload = TokenRegister(
        mint="MINT" + "x" * 28,
        creator_wallet="CRTR" + "y" * 28,
        symbol="VAULT",
        name="BagsVault Governance",
        decimals=9,
    )
    out = await service.register(payload)
    assert out.mint == payload.mint
    assert out.symbol == "VAULT"
    db.tokens.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_is_idempotent_for_same_creator() -> None:
    mint = "MINT" + "x" * 28
    creator = "CRTR" + "y" * 28
    db = _make_db(
        initial_tokens=[
            {
                "id": "abc",
                "mint": mint,
                "creator_wallet": creator,
                "symbol": "VAULT",
                "name": "BagsVault Governance",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": False,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    payload = TokenRegister(
        mint=mint,
        creator_wallet=creator,
        symbol="VAULT",
        name="BagsVault Governance",
    )
    out = await service.register(payload)
    assert out.mint == mint
    assert out.id == "abc"  # existing record returned
    db.tokens.insert_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_conflicts_on_different_creator() -> None:
    mint = "MINT" + "x" * 28
    db = _make_db(
        initial_tokens=[
            {
                "id": "abc",
                "mint": mint,
                "creator_wallet": "OWNER1" + "z" * 26,
                "symbol": "VAULT",
                "name": "BagsVault Governance",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": False,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    payload = TokenRegister(
        mint=mint,
        creator_wallet="OWNER2" + "q" * 26,
        symbol="VAULT",
        name="BagsVault Governance",
    )
    with pytest.raises(ConflictError) as ei:
        await service.register(payload)
    assert ei.value.details["registered_creator"] == "OWNER1" + "z" * 26


# ----------------------------------------------------------------------
# Service: vault lookup
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_vault_404_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vault_token_mint", "")
    db = _make_db()
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    with pytest.raises(NotFoundError) as ei:
        await service.get_vault()
    assert "VAULT_TOKEN_MINT" in str(ei.value.details)


@pytest.mark.asyncio
async def test_get_vault_returns_record_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    mint = "VAULTMINT" + "v" * 23
    monkeypatch.setattr(settings, "vault_token_mint", mint)
    db = _make_db(
        initial_tokens=[
            {
                "id": "vault-1",
                "mint": mint,
                "creator_wallet": "DAO" + "d" * 29,
                "symbol": "VAULT",
                "name": "BagsVault",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": True,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    out = await service.get_vault()
    assert out.mint == mint
    assert out.is_vault_token is True


# ----------------------------------------------------------------------
# Service: get_with_metadata
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_with_metadata_includes_live_data() -> None:
    mint = "MINT" + "x" * 28
    db = _make_db(
        initial_tokens=[
            {
                "id": "id1",
                "mint": mint,
                "creator_wallet": "CRTR" + "y" * 28,
                "symbol": "ABC",
                "name": "Abc",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": False,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    fake_client = _FakeBagsClient(metadata={"name": "Abc Live", "holders": 42})
    service = TokenService(db=db, client=fake_client)  # type: ignore[arg-type]
    out = await service.get_with_metadata(mint)
    assert out["mint"] == mint
    assert out["bags_metadata"] == {"name": "Abc Live", "holders": 42}


@pytest.mark.asyncio
async def test_get_with_metadata_handles_upstream_error() -> None:
    # Use a different mint to skip the in-process metadata cache.
    mint = "MINT" + "z" * 28
    db = _make_db(
        initial_tokens=[
            {
                "id": "id2",
                "mint": mint,
                "creator_wallet": "CRTR" + "y" * 28,
                "symbol": "ABC",
                "name": "Abc",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": False,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    fake_client = _FakeBagsClient(metadata=None)  # raises in get_token_metadata
    service = TokenService(db=db, client=fake_client)  # type: ignore[arg-type]
    out = await service.get_with_metadata(mint)
    assert out["bags_metadata"] is None
    assert "metadata_error" in out


# ----------------------------------------------------------------------
# Router-level
# ----------------------------------------------------------------------
def _make_app(service: TokenService, verified_wallet: str | None = None) -> FastAPI:
    """Build a router-only test app.

    ``verified_wallet`` overrides the SIWS auth dependency. Pass the value used
    as ``creator_wallet`` in the request body for happy paths, or a different
    string to exercise the body-vs-signer mismatch path.
    """

    from app.auth import require_wallet

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(tokens_router.router, prefix="/api")
    app.dependency_overrides[tokens_router.get_token_service] = lambda: service
    if verified_wallet is not None:
        app.dependency_overrides[require_wallet] = lambda: verified_wallet
    return app


@pytest.mark.asyncio
async def test_router_register_endpoint() -> None:
    db = _make_db()
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    creator = "CRTR" + "y" * 28
    app = _make_app(service, verified_wallet=creator)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/tokens/register",
            json={
                "mint": "MINT" + "x" * 28,
                "creator_wallet": creator,
                "symbol": "ABC",
                "name": "Abc Token",
                "decimals": 6,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "ABC"
    assert body["decimals"] == 6


@pytest.mark.asyncio
async def test_router_register_rejects_signer_body_mismatch() -> None:
    db = _make_db()
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    app = _make_app(service, verified_wallet="A" * 32)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/tokens/register",
            json={
                "mint": "MINT" + "x" * 28,
                "creator_wallet": "B" * 32,
                "symbol": "ABC",
                "name": "Abc Token",
                "decimals": 6,
            },
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_error"


@pytest.mark.asyncio
async def test_router_vault_404_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vault_token_mint", "")
    db = _make_db()
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens/vault")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_router_vault_returns_record(monkeypatch: pytest.MonkeyPatch) -> None:
    mint = "VAULTMINT" + "v" * 23
    monkeypatch.setattr(settings, "vault_token_mint", mint)
    db = _make_db(
        initial_tokens=[
            {
                "id": "vault-1",
                "mint": mint,
                "creator_wallet": "DAO" + "d" * 29,
                "symbol": "VAULT",
                "name": "BagsVault",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": True,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens/vault")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mint"] == mint
    assert body["is_vault_token"] is True


@pytest.mark.asyncio
async def test_router_list_tokens_pagination() -> None:
    db = _make_db(
        initial_tokens=[
            {
                "id": f"id{i}",
                "mint": f"MINT{i}" + "x" * 27,
                "creator_wallet": "CRTR" + "y" * 28,
                "symbol": f"T{i}",
                "name": f"Token {i}",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": False,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
            for i in range(3)
        ]
    )
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/tokens?limit=2&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["limit"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_router_register_conflict_returns_409() -> None:
    mint = "MINT" + "x" * 28
    db = _make_db(
        initial_tokens=[
            {
                "id": "abc",
                "mint": mint,
                "creator_wallet": "OWNER1" + "z" * 26,
                "symbol": "VAULT",
                "name": "v",
                "decimals": 9,
                "metadata_uri": None,
                "is_vault_token": False,
                "bags_metadata": None,
                "registered_at": "2024-05-02T00:00:00+00:00",
            }
        ]
    )
    service = TokenService(db=db, client=_FakeBagsClient())  # type: ignore[arg-type]
    new_creator = "OWNER2" + "q" * 26
    app = _make_app(service, verified_wallet=new_creator)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/tokens/register",
            json={
                "mint": mint,
                "creator_wallet": new_creator,
                "symbol": "VAULT",
                "name": "v",
            },
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"
