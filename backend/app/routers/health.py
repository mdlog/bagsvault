"""Liveness/readiness checks for Mongo and the Solana RPC endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

_RPC_TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=2.0, pool=2.0)


async def _check_mongo(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    try:
        await db.command("ping")
    except Exception as exc:  # noqa: BLE001 — health probe must never raise
        logger.warning("Mongo health check failed: %s", exc)
        return {"status": "down", "error": str(exc)}
    return {"status": "up"}


async def _check_solana_rpc() -> dict[str, Any]:
    """Use Solana JSON-RPC ``getHealth`` to probe the configured cluster.

    Treat unreachable / non-200 / non-OK responses as ``degraded`` rather than
    bubbling them as errors — health endpoints should never throw.
    """

    body = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
    try:
        async with httpx.AsyncClient(timeout=_RPC_TIMEOUT) as client:
            response = await client.post(settings.solana_rpc_url, json=body)
    except httpx.HTTPError as exc:
        logger.warning("Solana RPC health probe failed: %s", exc)
        return {"status": "down", "error": str(exc), "rpc_url": settings.solana_rpc_url}

    if response.status_code != 200:
        return {
            "status": "degraded",
            "http_status": response.status_code,
            "rpc_url": settings.solana_rpc_url,
        }

    try:
        data = response.json()
    except ValueError:
        return {"status": "degraded", "error": "non-json", "rpc_url": settings.solana_rpc_url}

    result = data.get("result") if isinstance(data, dict) else None
    if result == "ok":
        return {"status": "up", "rpc_url": settings.solana_rpc_url}
    return {
        "status": "degraded",
        "result": result,
        "rpc_url": settings.solana_rpc_url,
    }


@router.get("")
async def health(db: AsyncIOMotorDatabase = Depends(get_db)) -> dict[str, Any]:
    """Composite health check used by load balancers and the frontend."""

    mongo_check = await _check_mongo(db)
    solana_check = await _check_solana_rpc()

    overall = "ok"
    if mongo_check["status"] != "up" or solana_check["status"] != "up":
        overall = "degraded"

    return {
        "status": overall,
        "checks": {
            "mongo": mongo_check,
            "solana_rpc": solana_check,
        },
    }
