"""Deposit endpoints.

The frontend posts ``{commitment, amount, token, tx_signature, ...}``
once it has broadcast the on-chain deposit transaction. This router
verifies the transaction landed and persists the commitment for the
anonymity-set + recent-deposits views.

There is also a ``POST /deposits/build`` endpoint which compiles the
unsigned Anchor ``deposit`` instruction so the frontend can hand it
straight to the user's wallet. Bootstrapping the wallet adapter itself
is Phase 5 — for now the user pastes the resulting base64 tx into
``solana program send-tx`` (or any other tool) and POSTs the resulting
signature back via ``POST /deposits``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_wallet
from app.clients.solana_rpc import SolanaRpcClient, get_solana_rpc_client
from app.database import get_db
from app.models.commitment import Commitment, CommitmentCreate
from app.services.deposit_builder import DepositBuilder
from app.services.deposit_service import DepositService
from app.services.merkle_indexer import MerkleIndexer

router = APIRouter(prefix="/deposits", tags=["deposits"])


class DepositBuildRequest(BaseModel):
    """Request body for ``POST /deposits/build``."""

    model_config = ConfigDict(extra="ignore")

    commitment: str = Field(min_length=1, description="Hex-encoded Poseidon commitment.")
    amount: int = Field(ge=1, description="Amount in lamports / token base units.")
    token: str = Field(default="SOL", description="'SOL' or a base58 SPL mint pubkey.")
    depositor_pubkey: str = Field(min_length=32, description="Caller's wallet pubkey (signer).")


def get_deposit_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> DepositService:
    """Wire the deposit service with shared singletons."""

    indexer = MerkleIndexer(rpc=rpc, db=db)
    return DepositService(rpc=rpc, db=db, merkle=indexer)


def get_deposit_builder(
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> DepositBuilder:
    """Wire the deposit-ix builder with the shared RPC client."""

    return DepositBuilder(rpc=rpc)


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


@router.post("/build")
async def build_deposit_tx(
    payload: DepositBuildRequest,
    builder: DepositBuilder = Depends(get_deposit_builder),
) -> dict[str, Any]:
    """Compile the unsigned Anchor ``deposit`` transaction.

    The frontend forwards the returned ``tx_base64`` to the user's
    wallet for signing + broadcast. We never see the user's secret key.
    Returns ``{tx_base64, blockhash, tree_state_pda, vault_pda, ...}``.

    Note: this endpoint is intentionally NOT wallet-gated by
    ``require_wallet``. Building an unsigned tx leaks no secret state —
    anyone with the program ID could compile the same payload locally.
    Compliance gating happens at ``POST /api/compliance/scan`` upstream.
    """

    return await builder.build_unsigned_tx(
        commitment_hex=payload.commitment,
        amount_lamports=payload.amount,
        depositor=payload.depositor_pubkey,
        token_mint=payload.token,
    )
