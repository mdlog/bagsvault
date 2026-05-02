"""Anonymity-set + Merkle-root endpoints.

Both endpoints power frontend pages that need a quick read of
``commitments`` count + the latest known root. They are intentionally
tolerant: if the BagsVault program ID is not yet configured (no roots in
the cache), they fall back to the all-zeroes empty-tree root rather
than 503ing — the landing/withdraw views must always render.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clients.solana_rpc import SolanaRpcClient, get_solana_rpc_client
from app.config import settings
from app.database import get_db
from app.services.deposit_service import DepositService
from app.services.merkle_indexer import MerkleIndexer

router = APIRouter(tags=["anonymity"])

_FALLBACK_ROOT = "0" * 64
_RECENT_ROOTS_LIMIT = 10


def _make_indexer(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> MerkleIndexer:
    return MerkleIndexer(rpc=rpc, db=db)


def _make_deposit_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> DepositService:
    indexer = MerkleIndexer(rpc=rpc, db=db)
    return DepositService(rpc=rpc, db=db, merkle=indexer)


@router.get("/anonymity-set")
async def get_anonymity_set(
    service: DepositService = Depends(_make_deposit_service),
) -> dict[str, Any]:
    """Return ``{count, current_root, updated_at, source}`` for the pool."""

    return await service.get_anonymity_set()


@router.get("/merkle/root")
async def get_merkle_root(
    indexer: MerkleIndexer = Depends(_make_indexer),
) -> dict[str, Any]:
    """Return the current root + the 10 most recent roots from the cache."""

    recent = await indexer.get_recent_roots(limit=_RECENT_ROOTS_LIMIT)
    if recent:
        return {
            "current": recent[0].root,
            "recent": [r.root for r in recent],
            "source": recent[0].source,
            "program_id": settings.bagsvault_program_id,
        }
    return {
        "current": _FALLBACK_ROOT,
        "recent": [],
        "source": "fallback",
        "program_id": settings.bagsvault_program_id,
    }
