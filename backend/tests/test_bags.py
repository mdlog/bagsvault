"""Tests for the Bags API client + service + router."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.clients.bags_api import BagsAPIClient
from app.exceptions import ServiceUnavailableError, UpstreamError, register_exception_handlers
from app.routers import bags as bags_router
from app.services.bags_service import BagsService

BASE = "https://bags.test"


# ----------------------------------------------------------------------
# Client-level
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_raises_503_when_no_api_key() -> None:
    client = BagsAPIClient(api_key="", base_url=BASE)
    with pytest.raises(ServiceUnavailableError) as ei:
        await client.get_claimable_fees("Wallet")
    assert "BAGS_API_KEY" in str(ei.value.details)


@pytest.mark.asyncio
async def test_client_claim_tx_returns_payload() -> None:
    client = BagsAPIClient(api_key="test-key", base_url=BASE)
    payload = {"transactions": ["base64tx1", "base64tx2"], "pendingFees": []}
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{BASE}/token-launch/claim-txs/v3").respond(200, json=payload)
        result = await client.build_claim_tx("Wallet")
    assert result == payload
    await client.aclose()


@pytest.mark.asyncio
async def test_client_swap_quote_sends_expected_body() -> None:
    client = BagsAPIClient(api_key="test-key", base_url=BASE)
    expected_resp = {"route": [], "outAmount": 1000}
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{BASE}/trade/swap").respond(200, json=expected_resp)
        result = await client.get_swap_quote(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            amount=1_000_000_000,
            slippage_bps=75,
        )
    assert result == expected_resp
    sent = route.calls.last.request
    assert sent.method == "POST"
    body = sent.read().decode()
    assert "1000000000" in body
    assert "75" in body
    await client.aclose()


@pytest.mark.asyncio
async def test_client_raises_upstream_on_4xx() -> None:
    client = BagsAPIClient(api_key="test-key", base_url=BASE)
    with respx.mock() as router:
        router.post(f"{BASE}/trade/swap").respond(403, json={"error": "forbidden"})
        with pytest.raises(UpstreamError) as ei:
            await client.get_swap_quote("a", "b", 1)
    assert ei.value.details["status_code"] == 403
    await client.aclose()


@pytest.mark.asyncio
async def test_client_raises_upstream_on_network_error() -> None:
    client = BagsAPIClient(api_key="test-key", base_url=BASE)
    with respx.mock() as router:
        router.get(f"{BASE}/fee-share/v2/MintXyz").mock(side_effect=httpx.ConnectError("dns fail"))
        with pytest.raises(UpstreamError):
            await client.get_fee_share("MintXyz")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_ping_unconfigured() -> None:
    client = BagsAPIClient(api_key="", base_url=BASE)
    result = await client.ping()
    assert result["reachable"] is False
    assert result["configured"] is False


@pytest.mark.asyncio
async def test_client_ping_reachable() -> None:
    client = BagsAPIClient(api_key="test-key", base_url=BASE)
    with respx.mock() as router:
        router.get(f"{BASE}/").respond(200, text="ok")
        result = await client.ping()
    assert result["reachable"] is True
    assert result["configured"] is True
    await client.aclose()


@pytest.mark.asyncio
async def test_client_ping_network_error_does_not_raise() -> None:
    client = BagsAPIClient(api_key="test-key", base_url=BASE)
    with respx.mock() as router:
        router.get(f"{BASE}/").mock(side_effect=httpx.ConnectError("nope"))
        result = await client.ping()
    assert result["reachable"] is False
    assert "error" in result
    await client.aclose()


# ----------------------------------------------------------------------
# Service-level
# ----------------------------------------------------------------------
class _FakeBagsClient:
    def __init__(
        self,
        *,
        claim_response: dict[str, Any] | None = None,
        claimable_response: dict[str, Any] | None = None,
        ping_response: dict[str, Any] | None = None,
        swap_response: dict[str, Any] | None = None,
        fee_share_response: dict[str, Any] | None = None,
    ) -> None:
        self.claim_response = claim_response or {"transactions": []}
        self.claimable_response = claimable_response or {}
        self.ping_response = ping_response or {"reachable": True, "configured": True}
        self.swap_response = swap_response or {}
        self.fee_share_response = fee_share_response or {}

    async def ping(self) -> dict[str, Any]:
        return self.ping_response

    async def build_claim_tx(
        self, creator_wallet: str, token_mint: str | None = None
    ) -> dict[str, Any]:
        return self.claim_response

    async def get_claimable_fees(
        self, creator_wallet: str, token_mint: str | None = None
    ) -> dict[str, Any]:
        return self.claimable_response

    async def get_swap_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        return self.swap_response

    async def get_fee_share(self, token_mint: str) -> dict[str, Any]:
        return self.fee_share_response


@pytest.mark.asyncio
async def test_service_health_unconfigured() -> None:
    fake = _FakeBagsClient(ping_response={"reachable": False, "configured": False})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    out = await service.health()
    assert out["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_service_health_up() -> None:
    fake = _FakeBagsClient(ping_response={"reachable": True, "configured": True})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    out = await service.health()
    assert out["status"] == "up"


@pytest.mark.asyncio
async def test_service_health_down() -> None:
    fake = _FakeBagsClient(ping_response={"reachable": False, "configured": True, "error": "boom"})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    out = await service.health()
    assert out["status"] == "down"


@pytest.mark.asyncio
async def test_service_claim_fees_extracts_txs_and_pending() -> None:
    fake = _FakeBagsClient(
        claim_response={
            "transactions": ["b64tx-1", "b64tx-2"],
            "pendingFees": [{"mint": "So111", "amount": 247}],
        }
    )
    service = BagsService(client=fake)  # type: ignore[arg-type]
    result = await service.claim_fees("WalletAbc")
    assert result["unsigned_transactions"] == ["b64tx-1", "b64tx-2"]
    assert result["pending_fees"] == [{"mint": "So111", "amount": 247}]
    assert result["creator_wallet"] == "WalletAbc"


@pytest.mark.asyncio
async def test_service_claim_fees_falls_back_to_claimable_endpoint() -> None:
    fake = _FakeBagsClient(
        claim_response={"transactions": ["only-tx"]},  # no pending in claim resp
        claimable_response={"claimable": [{"mint": "BAGS", "amount": 18420}]},
    )
    service = BagsService(client=fake)  # type: ignore[arg-type]
    result = await service.claim_fees("WalletAbc")
    assert result["unsigned_transactions"] == ["only-tx"]
    assert result["pending_fees"] == [{"mint": "BAGS", "amount": 18420}]


@pytest.mark.asyncio
async def test_service_swap_quote_passes_through() -> None:
    fake = _FakeBagsClient(swap_response={"route": ["jup"], "outAmount": 1234})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    out = await service.swap_quote("a", "b", 1_000)
    assert out["outAmount"] == 1234


# ----------------------------------------------------------------------
# Router-level (end-to-end via ASGI transport)
# ----------------------------------------------------------------------
def _make_app(service: BagsService, verified_wallet: str | None = None) -> FastAPI:
    """Build a router-only test app.

    ``verified_wallet`` overrides the SIWS auth dependency so tests don't need
    to forge real signatures. Pass the same string used as ``creator_wallet``
    in the request body for happy-path tests; pass a different string to test
    the body-vs-signer mismatch path; pass ``None`` to leave auth unmocked
    (useful for the unconfigured-503 path which must short-circuit before auth).
    """

    from app.auth import require_wallet

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(bags_router.router, prefix="/api")
    app.dependency_overrides[bags_router.get_bags_service] = lambda: service
    if verified_wallet is not None:
        app.dependency_overrides[require_wallet] = lambda: verified_wallet
    return app


@pytest.mark.asyncio
async def test_router_health_returns_200_even_when_unconfigured() -> None:
    fake = _FakeBagsClient(ping_response={"reachable": False, "configured": False})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/bags/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_router_claim_fees_happy_path() -> None:
    fake = _FakeBagsClient(
        claim_response={
            "transactions": ["b64-tx"],
            "pendingFees": [{"mint": "So111", "amount": 100}],
        }
    )
    service = BagsService(client=fake)  # type: ignore[arg-type]
    wallet = "X" * 32
    app = _make_app(service, verified_wallet=wallet)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/bags/claim-fees",
            json={"creator_wallet": wallet},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["unsigned_transactions"] == ["b64-tx"]
    assert body["pending_fees"][0]["amount"] == 100


@pytest.mark.asyncio
async def test_router_claim_fees_rejects_signer_body_mismatch() -> None:
    fake = _FakeBagsClient(claim_response={"transactions": [], "pendingFees": []})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    app = _make_app(service, verified_wallet="A" * 32)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/bags/claim-fees",
            json={"creator_wallet": "B" * 32},
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_error"


@pytest.mark.asyncio
async def test_router_swap_quote_happy_path() -> None:
    fake = _FakeBagsClient(swap_response={"route": ["jup"], "outAmount": 500})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    app = _make_app(service, verified_wallet="X" * 32)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/bags/swap-quote",
            json={
                "input_mint": "S" * 32,
                "output_mint": "U" * 32,
                "amount": 1_000_000,
                "slippage_bps": 50,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["outAmount"] == 500


@pytest.mark.asyncio
async def test_router_fee_share_lookup() -> None:
    fake = _FakeBagsClient(fee_share_response={"creator": 9000, "vault": 1000})
    service = BagsService(client=fake)  # type: ignore[arg-type]
    app = _make_app(service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/bags/fee-share/MintXyz")
    assert resp.status_code == 200
    assert resp.json()["creator"] == 9000


@pytest.mark.asyncio
async def test_router_503_when_real_client_unconfigured() -> None:
    """Real client (no api key) plugged in -> claim-fees surfaces 503."""

    real_client = BagsAPIClient(api_key="")
    real_service = BagsService(client=real_client)
    wallet = "X" * 32
    app = _make_app(real_service, verified_wallet=wallet)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/bags/claim-fees", json={"creator_wallet": wallet})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"
