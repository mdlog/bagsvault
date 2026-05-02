"""Relayer registry endpoints.

The registry is a read-mostly surface — operators register their nodes
out-of-band via ``scripts/seed_relayers.py``, and these endpoints just
expose the live state to the frontend leaderboard and withdrawal
selector.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import get_db
from app.exceptions import NotFoundError
from app.services.relayer_service import RelayerService

router = APIRouter(prefix="/relayers", tags=["relayers"])

SortKey = Literal["uptime", "fee", "ping", "jobs"]


def get_relayer_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> RelayerService:
    return RelayerService(db=db)


@router.get("")
async def list_relayers(
    sort: SortKey = Query(default="uptime"),
    limit: int = Query(default=50, ge=1, le=200),
    service: RelayerService = Depends(get_relayer_service),
) -> dict[str, Any]:
    """List registered relayers with stats, sorted by the requested key."""

    relayers = await service.list_active(sort=sort, limit=limit)
    return {
        "items": [r.model_dump() for r in relayers],
        "sort": sort,
        "limit": limit,
        "count": len(relayers),
    }


@router.get("/{relayer_id}/stats")
async def relayer_stats(
    relayer_id: str,
    service: RelayerService = Depends(get_relayer_service),
) -> dict[str, Any]:
    """Live stats for a single relayer (404 if unregistered)."""

    relayer = await service.get(relayer_id)
    if not relayer:
        raise NotFoundError(
            f"No relayer registered with id {relayer_id}.",
            details={"relayer_id": relayer_id},
        )
    return await service.stats(relayer_id)
