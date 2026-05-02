"""Claim-fees-then-deposit orchestrator.

Architecture doc Section 2.B promises that a creator can claim Bags fees
"langsung ke dalam BagsVault secara anonim" — i.e. the claimed lamports
land in the privacy pool's vault PDA without ever passing through a
wallet that's correlated with the creator's public identity.

The flow this service exposes:

    1. Call ``BagsAPIClient.build_claim_tx(creator_wallet, token_mint)``
       to fetch one or more unsigned base64 transactions that move the
       claimable fee balance into ``creator_wallet``. Bags returns these
       as opaque blobs we don't try to parse — the route, claim PDAs,
       and any associated-token-account creation are all upstream's job.
    2. Build an Anchor ``deposit(commitment)`` ix targeting the privacy
       pool keyed on ``token_mint``. The depositor on this ix is the
       ``creator_wallet``: that's the only key that holds the freshly
       claimed funds, and it's also the same key the upstream claim tx
       just touched, so submitting both back-to-back leaves a tight pair
       of signatures from the same wallet — by design. Once the deposit
       lands, anonymity is conferred by the anonymity set, not the
       wallet ownership relationship.

Like :mod:`swap_to_deposit_service`, this service NEVER signs or
broadcasts. The user's wallet signs every tx in order: all claim txs
first, then the deposit tx.
"""

from __future__ import annotations

import logging
from typing import Any

from app.clients.bags_api import BagsAPIClient
from app.config import settings
from app.exceptions import ServiceUnavailableError
from app.services.bags_service import _extract_unsigned_txs
from app.services.swap_to_deposit_service import (
    _decode_pubkey,
    _hex_to_bytes32,
    _serialize_unsigned_tx,
    build_deposit_ix,
)

logger = logging.getLogger(__name__)


class ClaimToDepositService:
    """Build (claim_txs..., deposit_tx) for the wallet to sign in order."""

    def __init__(self, bags_client: BagsAPIClient) -> None:
        self._bags = bags_client

    async def build_chain(
        self,
        *,
        creator_wallet: str,
        token_mint: str,
        commitment_hex: str,
    ) -> dict[str, Any]:
        """Return a dict carrying the claim batch + the deposit tx.

        Shape:

            {
                "claim_txs": ["<base64>", ...],   # one or more, in order
                "deposit_tx": "<base64>",
                "claim_raw": {...},               # raw upstream payload
                "deposit_program_id": "<base58>",
                "deposit_token_mint": "<base58>",
                "creator_wallet": "<base58>",
            }

        The ``claim_txs`` array is forwarded as Bags returned it — we
        don't reorder or merge them. Wallets that batch-sign should
        respect the array order, otherwise the claim PDA dance can fail.
        """

        if not settings.bagsvault_program_id:
            raise ServiceUnavailableError(
                "BAGSVAULT_PROGRAM_ID is not configured.",
                details={"missing_env": "BAGSVAULT_PROGRAM_ID"},
            )
        program_id = _decode_pubkey(
            settings.bagsvault_program_id, label="BAGSVAULT_PROGRAM_ID"
        )

        creator_pubkey = _decode_pubkey(creator_wallet, label="creator_wallet")
        token_mint_pubkey = _decode_pubkey(token_mint, label="token_mint")
        commitment = _hex_to_bytes32(commitment_hex, label="commitment_hex")

        # 1. Pull the unsigned claim tx(s) from Bags.
        claim_raw = await self._bags.build_claim_tx(creator_wallet, token_mint)
        claim_txs = _extract_unsigned_txs(claim_raw)
        if not claim_txs:
            raise ServiceUnavailableError(
                "Bags claim response did not include any unsigned transactions.",
                details={"upstream": "bags", "keys": sorted(claim_raw.keys())},
            )

        # 2. Build the deposit ix. The depositor is the creator wallet —
        #    it's the same key Bags' claim tx targets, which keeps the
        #    "claim → deposit" pair atomic from the wallet's perspective.
        deposit_ix = build_deposit_ix(
            program_id=program_id,
            token_mint=token_mint_pubkey,
            depositor=creator_pubkey,
            commitment_bytes32=commitment,
        )
        deposit_tx_b64 = _serialize_unsigned_tx(deposit_ix, creator_pubkey)

        logger.info(
            "claim_to_deposit.build_chain creator=%s mint=%s claim_tx_count=%d",
            creator_wallet,
            token_mint,
            len(claim_txs),
        )

        return {
            "claim_txs": claim_txs,
            "deposit_tx": deposit_tx_b64,
            "claim_raw": claim_raw,
            "deposit_program_id": str(program_id),
            "deposit_token_mint": str(token_mint_pubkey),
            "creator_wallet": str(creator_pubkey),
        }


__all__ = ["ClaimToDepositService"]
