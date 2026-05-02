"""Bags integration endpoints: claim fees, swap quotes, fee-share lookup."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_wallet
from app.clients.bags_api import BagsAPIClient, get_bags_api_client
from app.exceptions import AuthError
from app.services.bags_service import BagsService
from app.services.claim_to_deposit_service import ClaimToDepositService
from app.services.swap_to_deposit_service import SwapToDepositService

router = APIRouter(prefix="/bags", tags=["bags"])


def get_bags_service(
    client: BagsAPIClient = Depends(get_bags_api_client),
) -> BagsService:
    return BagsService(client=client)


def get_swap_to_deposit_service(
    client: BagsAPIClient = Depends(get_bags_api_client),
) -> SwapToDepositService:
    return SwapToDepositService(bags_client=client)


def get_claim_to_deposit_service(
    client: BagsAPIClient = Depends(get_bags_api_client),
) -> ClaimToDepositService:
    return ClaimToDepositService(bags_client=client)


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------
class ClaimFeesRequest(BaseModel):
    creator_wallet: str = Field(min_length=20, max_length=64, description="Solana wallet pubkey")
    token_mint: str | None = Field(
        default=None,
        min_length=20,
        max_length=64,
        description="Optional token mint to scope the claim",
    )


class SwapQuoteRequest(BaseModel):
    input_mint: str = Field(min_length=20, max_length=64)
    output_mint: str = Field(min_length=20, max_length=64)
    amount: int = Field(gt=0, description="Amount in input-token smallest unit (lamports)")
    slippage_bps: int = Field(default=50, ge=0, le=10_000)


class SwapToDepositRequest(BaseModel):
    """Inputs to the chained swap-then-deposit orchestrator.

    The depositor pubkey must equal the SIWS-authenticated wallet — see
    the endpoint handler. ``commitment_hex`` is the Poseidon commitment
    leaf the deposit will publish, computed client-side via
    ``POST /api/proofs/commitment``.
    """

    input_mint: str = Field(min_length=20, max_length=64)
    output_mint: str = Field(min_length=20, max_length=64)
    amount_in: int = Field(gt=0, description="Amount in input-token smallest unit")
    slippage_bps: int = Field(default=50, ge=0, le=10_000)
    depositor_pubkey: str = Field(min_length=20, max_length=64)
    commitment_hex: str = Field(
        min_length=2,
        max_length=66,
        description="Hex-encoded 32-byte Poseidon commitment (with or without 0x).",
    )


class ClaimToDepositRequest(BaseModel):
    """Inputs to the chained claim-fees-then-deposit orchestrator."""

    creator_wallet: str = Field(min_length=20, max_length=64)
    token_mint: str = Field(min_length=20, max_length=64)
    commitment_hex: str = Field(
        min_length=2,
        max_length=66,
        description="Hex-encoded 32-byte Poseidon commitment (with or without 0x).",
    )


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
@router.get("/health")
async def health(service: BagsService = Depends(get_bags_service)) -> dict[str, Any]:
    """Probe Bags API connectivity. Always 200; status is in the body."""

    return await service.health()


@router.post("/claim-fees")
async def claim_fees(
    payload: ClaimFeesRequest,
    service: BagsService = Depends(get_bags_service),
    wallet: str = Depends(require_wallet),
) -> dict[str, Any]:
    """Build unsigned claim transactions for ``creator_wallet`` to sign client-side.

    Returns ``{"unsigned_transactions": [...], "pending_fees": [...], ...}``.
    The backend NEVER signs or broadcasts — wallets sign and submit.

    Authenticated: the request must carry a valid SIWS signature whose pubkey
    matches ``creator_wallet``. We refuse to build claim txs for a wallet the
    caller hasn't proven ownership of.
    """

    if wallet != payload.creator_wallet:
        raise AuthError(
            "Signed wallet does not match creator_wallet in request body.",
            details={"signed": wallet, "requested": payload.creator_wallet},
        )
    return await service.claim_fees(payload.creator_wallet, payload.token_mint)


@router.post("/swap-quote")
async def swap_quote(
    payload: SwapQuoteRequest,
    service: BagsService = Depends(get_bags_service),
    wallet: str = Depends(require_wallet),  # noqa: ARG001 — used to gate access only
) -> dict[str, Any]:
    """Fetch a swap quote + unsigned route transaction from Bags.

    Authenticated: any verified wallet may request quotes (no body-vs-signer
    binding required since quotes are read-only).
    """

    return await service.swap_quote(
        input_mint=payload.input_mint,
        output_mint=payload.output_mint,
        amount=payload.amount,
        slippage_bps=payload.slippage_bps,
    )


@router.post("/swap-to-deposit")
async def swap_to_deposit(
    payload: SwapToDepositRequest,
    service: SwapToDepositService = Depends(get_swap_to_deposit_service),
    wallet: str = Depends(require_wallet),
) -> dict[str, Any]:
    """Build (swap_tx, deposit_tx) for the wallet to sign in order.

    Authenticated: the depositor pubkey in the request body MUST equal
    the SIWS-authenticated wallet. We refuse to build a deposit
    instruction whose signer the caller hasn't proven ownership of —
    otherwise an attacker could craft a deposit tx that strands the
    user's swap output in a commitment they don't control.
    """

    if wallet != payload.depositor_pubkey:
        raise AuthError(
            "Signed wallet does not match depositor_pubkey in request body.",
            details={"signed": wallet, "requested": payload.depositor_pubkey},
        )
    return await service.build_chain(
        input_mint=payload.input_mint,
        output_mint=payload.output_mint,
        amount_in=payload.amount_in,
        slippage_bps=payload.slippage_bps,
        depositor_pubkey=payload.depositor_pubkey,
        commitment_hex=payload.commitment_hex,
    )


@router.post("/claim-to-deposit")
async def claim_to_deposit(
    payload: ClaimToDepositRequest,
    service: ClaimToDepositService = Depends(get_claim_to_deposit_service),
    wallet: str = Depends(require_wallet),
) -> dict[str, Any]:
    """Build (claim_txs..., deposit_tx) for the creator to sign in order.

    Authenticated: ``creator_wallet`` must equal the SIWS-authenticated
    pubkey. The same boundary as ``/api/bags/claim-fees`` — we refuse to
    build claim transactions for a wallet the caller hasn't proven
    ownership of.
    """

    if wallet != payload.creator_wallet:
        raise AuthError(
            "Signed wallet does not match creator_wallet in request body.",
            details={"signed": wallet, "requested": payload.creator_wallet},
        )
    return await service.build_chain(
        creator_wallet=payload.creator_wallet,
        token_mint=payload.token_mint,
        commitment_hex=payload.commitment_hex,
    )


@router.get("/fee-share/{mint}")
async def fee_share(mint: str, service: BagsService = Depends(get_bags_service)) -> dict[str, Any]:
    """Read the configured Fee Share V2 distribution for ``mint``.

    Backed by the Bags Fee Share V2 program
    ``FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`` per
    https://docs.bags.fm/principles/program-ids.
    """

    return await service.fee_share(mint)
