"""Bags integration endpoints: claim fees, swap quotes, fee-share lookup."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_wallet  # noqa: F401  # phase-2: attach as Depends.
from app.clients.bags_api import BagsAPIClient, get_bags_api_client
from app.services.bags_service import BagsService

router = APIRouter(prefix="/bags", tags=["bags"])


def get_bags_service(
    client: BagsAPIClient = Depends(get_bags_api_client),
) -> BagsService:
    return BagsService(client=client)


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
) -> dict[str, Any]:
    """Build unsigned claim transactions for ``creator_wallet`` to sign client-side.

    Returns ``{"unsigned_transactions": [...], "pending_fees": [...], ...}``.
    The backend NEVER signs or broadcasts — wallets sign and submit.
    """

    # TODO(phase-2): require_wallet — verify creator_wallet matches signer.
    return await service.claim_fees(payload.creator_wallet, payload.token_mint)


@router.post("/swap-quote")
async def swap_quote(
    payload: SwapQuoteRequest,
    service: BagsService = Depends(get_bags_service),
) -> dict[str, Any]:
    """Fetch a swap quote + unsigned route transaction from Bags."""

    # TODO(phase-2): require_wallet — verify quote requester.
    return await service.swap_quote(
        input_mint=payload.input_mint,
        output_mint=payload.output_mint,
        amount=payload.amount,
        slippage_bps=payload.slippage_bps,
    )


@router.get("/fee-share/{mint}")
async def fee_share(mint: str, service: BagsService = Depends(get_bags_service)) -> dict[str, Any]:
    """Read the configured Fee Share V2 distribution for ``mint``.

    Backed by the Bags Fee Share V2 program
    ``FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`` per
    https://docs.bags.fm/principles/program-ids.
    """

    return await service.fee_share(mint)
