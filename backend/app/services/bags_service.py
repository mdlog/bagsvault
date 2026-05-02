"""Bags service: orchestrates Bags API calls for the FastAPI router layer.

Keeps the router thin: every endpoint delegates here. The service owns
shape-normalization (e.g. ensuring claim responses always carry both an
``unsigned_transactions`` array and a ``pending_fees`` array so the
frontend can render a consistent UI even when the upstream payload
shifts).
"""

from __future__ import annotations

import logging
from typing import Any

from app.clients.bags_api import BagsAPIClient

logger = logging.getLogger(__name__)


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _extract_unsigned_txs(raw: dict[str, Any]) -> list[str]:
    """Pull base64-encoded unsigned txs out of a Bags claim response.

    The exact key Bags uses is not formally documented; we look at the
    most likely candidates in priority order. Returns an empty list when
    nothing matches so the frontend can still render a "nothing to claim"
    state without erroring.
    """

    for key in ("transactions", "txs", "unsignedTransactions", "unsigned_transactions"):
        if key in raw:
            items = _coerce_list(raw[key])
            return [str(item) for item in items if item is not None]
    # Single-tx shape.
    if isinstance(raw.get("transaction"), str):
        return [raw["transaction"]]
    return []


def _extract_pending_fees(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort extraction of pending claimable fees per token."""

    for key in ("pendingFees", "pending_fees", "claimable", "fees"):
        items = raw.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


class BagsService:
    """Coordinator around the Bags API client."""

    def __init__(self, client: BagsAPIClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        """Probe Bags API connectivity. Never raises.

        Returns a dict shaped ``{"status": "up"|"down"|"unconfigured",
        "details": {...}}`` so the router can return it verbatim with HTTP
        200 — the frontend uses ``status`` to render banners.
        """

        ping = await self._client.ping()
        if not ping.get("configured"):
            return {"status": "unconfigured", "details": ping}
        if not ping.get("reachable"):
            return {"status": "down", "details": ping}
        return {"status": "up", "details": ping}

    # ------------------------------------------------------------------
    # Claim fees
    # ------------------------------------------------------------------
    async def claim_fees(
        self, creator_wallet: str, token_mint: str | None = None
    ) -> dict[str, Any]:
        """Build claim transactions + return pending fee summary.

        Returns ``{"unsigned_transactions": [b64...], "pending_fees":
        [{"mint", "amount", ...}], "raw": {...}}``. The unsigned txs MUST
        be signed and broadcast client-side — the backend never holds a
        creator's keys.
        """

        # We call both endpoints so callers get a single round trip from
        # their perspective. If the "claimable" endpoint fails (or doesn't
        # exist for the given key), we still return the txs.
        claim_raw = await self._client.build_claim_tx(creator_wallet, token_mint)

        pending: list[dict[str, Any]] = _extract_pending_fees(claim_raw)
        if not pending:
            try:
                claimable_raw = await self._client.get_claimable_fees(creator_wallet, token_mint)
                pending = _extract_pending_fees(claimable_raw)
                if not pending and isinstance(claimable_raw.get("data"), list):
                    pending = [item for item in claimable_raw["data"] if isinstance(item, dict)]
            except Exception as exc:  # noqa: BLE001 — claimable lookup is best-effort
                logger.info(
                    "claimable lookup failed (non-fatal) for wallet=%s: %s",
                    creator_wallet,
                    exc,
                )

        return {
            "creator_wallet": creator_wallet,
            "token_mint": token_mint,
            "unsigned_transactions": _extract_unsigned_txs(claim_raw),
            "pending_fees": pending,
            "raw": claim_raw,
        }

    # ------------------------------------------------------------------
    # Swap
    # ------------------------------------------------------------------
    async def swap_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        """Get a swap quote + unsigned transaction route from Bags."""

        return await self._client.get_swap_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
            slippage_bps=slippage_bps,
        )

    # ------------------------------------------------------------------
    # Fee share
    # ------------------------------------------------------------------
    async def fee_share(self, token_mint: str) -> dict[str, Any]:
        """Read the Fee Share V2 distribution config for ``token_mint``."""

        return await self._client.get_fee_share(token_mint)
