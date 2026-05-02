"""Withdrawal endpoints.

Withdrawals are intentionally *not* gated by ``require_wallet`` — the
ZK proof itself is the auth, so anyone holding a valid proof + matching
nullifier may submit (the recipient address is part of the proof's
public inputs and locked to the proof). This is the same trust model
used by Tornado Cash and Sunspot.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clients.solana_rpc import SolanaRpcClient, get_solana_rpc_client
from app.clients.solana_signer import SolanaSignerClient, get_solana_signer_client
from app.database import get_db
from app.models.withdrawal import WithdrawalRelayRequest
from app.services.relayer_service import RelayerService
from app.services.withdrawal_service import WithdrawalService

router = APIRouter(prefix="/withdrawals", tags=["withdrawals"])


def get_withdrawal_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
    signer: SolanaSignerClient = Depends(get_solana_signer_client),
) -> WithdrawalService:
    relayers = RelayerService(db=db)
    return WithdrawalService(rpc=rpc, signer=signer, relayers=relayers, db=db)


@router.post("/relay")
async def relay_withdrawal(
    payload: WithdrawalRelayRequest,
    service: WithdrawalService = Depends(get_withdrawal_service),
) -> dict[str, Any]:
    """Build, sign, and broadcast a withdrawal transaction.

    The eight-step pipeline is documented on
    :meth:`WithdrawalService.relay`. Returns the base58 ``signature``
    once the Solana RPC accepts the transaction.
    """

    return await service.relay(payload)


@router.get("/recent")
async def recent_withdrawals(
    limit: int = Query(default=20, ge=1, le=100),
    service: WithdrawalService = Depends(get_withdrawal_service),
) -> dict[str, Any]:
    """Anonymized recent withdrawals for the live feed on the Relayers page."""

    items = await service.list_recent(limit=limit)
    return {"items": items, "limit": limit, "count": len(items)}
