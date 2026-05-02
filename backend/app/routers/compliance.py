"""Compliance endpoints: real Range Risk-backed wallet screening."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.clients.range_risk import RangeRiskClient, get_range_risk_client
from app.database import get_db
from app.models.risk_scan import RiskScan
from app.services.compliance_service import ComplianceService

router = APIRouter(prefix="/compliance", tags=["compliance"])


class ScanRequest(BaseModel):
    address: str = Field(min_length=20, max_length=64, description="Solana wallet pubkey")


def get_compliance_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    client: RangeRiskClient = Depends(get_range_risk_client),
) -> ComplianceService:
    return ComplianceService(db=db, client=client)


@router.post("/scan", response_model=RiskScan)
async def scan_address(
    payload: ScanRequest,
    service: ComplianceService = Depends(get_compliance_service),
) -> RiskScan:
    """Run a fresh Range Risk scan and cache the verdict."""

    return await service.scan(payload.address)


@router.get("/scan/{address}", response_model=RiskScan)
async def get_cached_scan(
    address: str,
    service: ComplianceService = Depends(get_compliance_service),
) -> RiskScan:
    """Return the cached scan for ``address`` (404 if none exists)."""

    return await service.get_cached(address)


@router.get("/stats")
async def stats(
    service: ComplianceService = Depends(get_compliance_service),
) -> dict[str, Any]:
    """Aggregate verdict counts shown on the Compliance dashboard."""

    return await service.stats()
