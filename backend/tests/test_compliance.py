"""Tests for the Range Risk client + compliance service + router."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.clients.range_risk import RangeRiskClient
from app.exceptions import (
    BagsVaultError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamError,
    register_exception_handlers,
)
from app.models.risk_scan import RiskScan
from app.routers import compliance as compliance_router
from app.services.compliance_service import ComplianceService


@pytest.mark.asyncio
async def test_client_raises_503_when_no_api_key() -> None:
    client = RangeRiskClient(api_key="")
    with pytest.raises(ServiceUnavailableError) as ei:
        await client.scan_address("Abc123")
    assert "RANGE_API_KEY" in str(ei.value.details)


@pytest.mark.asyncio
async def test_client_returns_payload_on_success() -> None:
    client = RangeRiskClient(api_key="test-key", base_url="https://range.test")
    payload = {"score": 12, "verdict": "APPROVE", "flags": []}

    with respx.mock(assert_all_called=True) as router:
        router.post("https://range.test/v1/risk/score").respond(200, json=payload)
        result = await client.scan_address("SoLAddrxx" * 4)

    assert result == payload
    await client.aclose()


@pytest.mark.asyncio
async def test_client_raises_upstream_on_4xx() -> None:
    client = RangeRiskClient(api_key="test-key", base_url="https://range.test")
    with respx.mock() as router:
        router.post("https://range.test/v1/risk/score").respond(403, json={"error": "forbidden"})
        with pytest.raises(UpstreamError) as ei:
            await client.scan_address("addr")
    assert ei.value.details["status_code"] == 403
    await client.aclose()


@pytest.mark.asyncio
async def test_client_raises_upstream_on_network_error() -> None:
    client = RangeRiskClient(api_key="test-key", base_url="https://range.test")
    with respx.mock() as router:
        router.post("https://range.test/v1/risk/score").mock(
            side_effect=httpx.ConnectError("dns fail")
        )
        with pytest.raises(UpstreamError):
            await client.scan_address("addr")
    await client.aclose()


@pytest.mark.asyncio
async def test_service_scan_caches_result(fake_db) -> None:
    class FakeClient:
        async def scan_address(self, address: str) -> dict[str, Any]:
            return {"score": 8, "verdict": "APPROVE"}

    service = ComplianceService(db=fake_db, client=FakeClient())  # type: ignore[arg-type]
    scan = await service.scan("WalletAbc")
    assert scan.verdict == "APPROVE"
    assert scan.score == 8
    fake_db.risk_scans.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_get_cached_returns_scan(fake_db) -> None:
    fake_db.risk_scans.find_one.return_value = {
        "id": "abc",
        "address": "Wallet",
        "score": 5,
        "verdict": "APPROVE",
        "flags": [],
        "checks": [],
        "scanned_at": "2024-05-02T00:00:00+00:00",
    }
    service = ComplianceService(db=fake_db, client=None)  # type: ignore[arg-type]
    scan = await service.get_cached("Wallet")
    assert scan.address == "Wallet"


@pytest.mark.asyncio
async def test_service_get_cached_404(fake_db) -> None:
    fake_db.risk_scans.find_one.return_value = None
    service = ComplianceService(db=fake_db, client=None)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.get_cached("Wallet")


@pytest.mark.asyncio
async def test_service_stats_aggregates(fake_db, fake_aggregate_cursor) -> None:
    fake_db.risk_scans.aggregate.return_value = fake_aggregate_cursor(
        [
            {"_id": "APPROVE", "count": 10},
            {"_id": "REVIEW", "count": 2},
            {"_id": "BLOCK", "count": 1},
        ]
    )
    service = ComplianceService(db=fake_db, client=None)  # type: ignore[arg-type]
    stats = await service.stats()
    assert stats == {
        "total_scans": 13,
        "approvals": 10,
        "reviews": 2,
        "blocks": 1,
        "false_positive_rate": 0.0,
    }


def test_riskscan_from_range_response_thresholds() -> None:
    low = RiskScan.from_range_response("a", {"score": 5})
    mid = RiskScan.from_range_response("a", {"score": 30})
    hi = RiskScan.from_range_response("a", {"score": 80, "flags": ["OFAC"]})
    assert low.verdict == "APPROVE"
    assert mid.verdict == "REVIEW"
    assert hi.verdict == "BLOCK"
    assert "OFAC" in hi.flags


def test_riskscan_from_range_normalized_zero_to_one() -> None:
    scan = RiskScan.from_range_response("a", {"risk_score": 0.85})
    assert scan.score == 85
    assert scan.verdict == "BLOCK"


def test_riskscan_handles_missing_fields() -> None:
    scan = RiskScan.from_range_response("a", {})
    assert scan.score == 0
    assert scan.verdict == "APPROVE"
    assert len(scan.checks) > 0  # default scaffold


@pytest.mark.asyncio
async def test_router_scan_endpoint_via_app(fake_db) -> None:
    """End-to-end: POST /api/compliance/scan with a mocked Range client."""

    app = FastAPI()
    register_exception_handlers(app)

    class FakeClient:
        async def scan_address(self, address: str) -> dict[str, Any]:
            return {"score": 70, "verdict": "BLOCK", "flags": ["OFAC"]}

    app.include_router(compliance_router.router, prefix="/api")
    app.dependency_overrides[compliance_router.get_compliance_service] = lambda: ComplianceService(
        db=fake_db, client=FakeClient()
    )  # type: ignore[arg-type]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/compliance/scan", json={"address": "X" * 32})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "BLOCK"
    assert body["score"] == 70


@pytest.mark.asyncio
async def test_router_503_when_api_key_missing() -> None:
    """If the real client (no api key) is plugged in, the endpoint surfaces 503."""

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(compliance_router.router, prefix="/api")

    real_client = RangeRiskClient(api_key="")

    class _DB:
        def __getattr__(self, name: str) -> Any:  # pragma: no cover - never called
            raise AssertionError(f"DB shouldn't be touched, got {name!r}")

    app.dependency_overrides[compliance_router.get_compliance_service] = lambda: ComplianceService(
        db=_DB(), client=real_client
    )  # type: ignore[arg-type]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/compliance/scan", json={"address": "X" * 32})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"


def test_bagsvault_error_subclasses() -> None:
    """Sanity: error classes have stable codes used by frontend."""

    assert BagsVaultError("x").code == "internal_error"
    assert NotFoundError("x").status_code == 404
