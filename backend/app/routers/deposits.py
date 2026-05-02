"""Deposit endpoints.

The frontend posts ``{commitment, amount, token, tx_signature, ...}``
once it has broadcast the on-chain deposit transaction. This router
verifies the transaction landed and persists the commitment for the
anonymity-set + recent-deposits views.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth import require_wallet
from app.clients.solana_rpc import SolanaRpcClient, get_solana_rpc_client
from app.database import get_db
from app.models.commitment import Commitment, CommitmentCreate
from app.services.deposit_service import DepositService
from app.services.merkle_indexer import MerkleIndexer

router = APIRouter(prefix="/deposits", tags=["deposits"])


def get_deposit_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> DepositService:
    """Wire the deposit service with shared singletons."""

    indexer = MerkleIndexer(rpc=rpc, db=db)
    return DepositService(rpc=rpc, db=db, merkle=indexer)


@router.post("", response_model=Commitment)
async def register_deposit(
    payload: CommitmentCreate,
    _wallet: str = Depends(require_wallet),
    service: DepositService = Depends(get_deposit_service),
) -> Commitment:
    """Verify the on-chain deposit tx and persist the commitment.

    Idempotent on ``commitment``. Conflict if the same commitment is
    re-submitted with a different ``tx_signature``.
    """

    return await service.register(
        commitment=payload.commitment,
        amount=payload.amount,
        token=payload.token,
        tx_signature=payload.tx_signature,
        creator_wallet=payload.creator_wallet,
    )


@router.get("/recent")
async def list_recent_deposits(
    limit: int = Query(default=20, ge=1, le=100),
    service: DepositService = Depends(get_deposit_service),
) -> list[dict[str, Any]]:
    """Return the most recent commitments in anonymized form."""

    return await service.list_recent(limit=limit)
