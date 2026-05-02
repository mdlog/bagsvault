"""Async wrapper around the Solana JSON-RPC API.

This client is BagsVault's single entry point for direct Solana node
interactions: confirming deposit transactions, reading the on-chain
Merkle-tree state account, and (for Agent B) building/sending withdrawal
transactions through a relayer.

Implementation notes:
* Uses ``httpx.AsyncClient`` directly — no ``solana-py`` SDK dependency.
  This keeps the surface auditable and avoids pulling in heavy transitive
  imports for what is essentially a thin POST wrapper.
* ``settings.solana_rpc_url`` always carries a default (devnet), so unlike
  :class:`app.clients.range_risk.RangeRiskClient` we **never** raise
  ``ServiceUnavailableError`` from this client. Endpoints that need a
  configured ``BAGSVAULT_PROGRAM_ID`` raise 503 themselves.
* JSON-RPC errors and non-2xx HTTP responses are normalized to
  :class:`UpstreamError` (HTTP 502) so the FastAPI exception handlers
  surface them with a stable shape.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.exceptions import UpstreamError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=10.0)


class SolanaRpcClient:
    """Thin async wrapper around the Solana JSON-RPC interface.

    The client lazily creates a single ``httpx.AsyncClient`` and reuses it
    for the lifetime of the process. Call :meth:`aclose` on shutdown if you
    want to release the underlying connection pool deterministically.
    """

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        commitment: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._rpc_url = (rpc_url or settings.solana_rpc_url).rstrip("/")
        self._commitment = commitment or settings.solana_commitment
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._rpc_url,
                timeout=self._timeout,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "bagsvault-backend/0.1",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------
    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        """Dispatch a single JSON-RPC method and return the ``result`` field.

        Raises :class:`UpstreamError` on transport failures, non-2xx HTTP
        responses, and JSON-RPC ``error`` envelopes. The caller is
        responsible for any further validation of the result shape.
        """

        client = self._get_client()
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or [],
        }

        try:
            response = await client.post("", json=body)
        except httpx.HTTPError as exc:
            logger.exception("Solana RPC network error on method=%s", method)
            raise UpstreamError(
                "Failed to reach Solana RPC.",
                details={"upstream": "solana_rpc", "method": method, "error": str(exc)},
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "Solana RPC HTTP %s for method=%s: %s",
                response.status_code,
                method,
                response.text[:500],
            )
            raise UpstreamError(
                f"Solana RPC returned HTTP {response.status_code}.",
                details={
                    "upstream": "solana_rpc",
                    "method": method,
                    "status_code": response.status_code,
                    "body": response.text[:1000],
                },
            )

        try:
            envelope = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "Solana RPC returned a non-JSON body.",
                details={"upstream": "solana_rpc", "method": method, "body": response.text[:500]},
            ) from exc

        if not isinstance(envelope, dict):
            raise UpstreamError(
                "Solana RPC returned an unexpected JSON shape.",
                details={
                    "upstream": "solana_rpc",
                    "method": method,
                    "type": type(envelope).__name__,
                },
            )

        if "error" in envelope and envelope["error"] is not None:
            err = envelope["error"]
            logger.warning("Solana RPC error envelope for method=%s: %s", method, err)
            raise UpstreamError(
                "Solana RPC returned an error envelope.",
                details={"upstream": "solana_rpc", "method": method, "rpc_error": err},
            )

        return envelope.get("result")

    # ------------------------------------------------------------------
    # Public API — read methods
    # ------------------------------------------------------------------
    async def get_health(self) -> str:
        """Return the result string for the ``getHealth`` JSON-RPC method."""

        result = await self._call("getHealth", [])
        return str(result) if result is not None else ""

    async def get_slot(self, commitment: str | None = None) -> int:
        """Return the most recent slot at the requested commitment level.

        Wraps the ``getSlot`` JSON-RPC method.
        """

        params: list[Any] = [{"commitment": commitment or self._commitment}]
        result = await self._call("getSlot", params)
        if not isinstance(result, int):
            raise UpstreamError(
                "Solana RPC getSlot returned non-integer result.",
                details={"upstream": "solana_rpc", "result": result},
            )
        return result

    async def get_transaction(
        self,
        signature_b58: str,
        max_supported_transaction_version: int = 0,
    ) -> dict[str, Any] | None:
        """Fetch a confirmed transaction by signature.

        Wraps the ``getTransaction`` JSON-RPC method with ``encoding=json``.
        Returns the full RPC ``result`` dict when found, or ``None`` if the
        node does not yet have the transaction (commonly because it is
        still propagating or not yet finalized at the requested commitment).
        """

        params: list[Any] = [
            signature_b58,
            {
                "encoding": "json",
                "commitment": self._commitment,
                "maxSupportedTransactionVersion": max_supported_transaction_version,
            },
        ]
        result = await self._call("getTransaction", params)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise UpstreamError(
                "Solana RPC getTransaction returned non-dict result.",
                details={"upstream": "solana_rpc", "result_type": type(result).__name__},
            )
        return result

    async def get_account_info(
        self,
        pubkey_b58: str,
        encoding: str = "base64",
    ) -> dict[str, Any] | None:
        """Return the account data for ``pubkey_b58`` or ``None`` if missing.

        Wraps the ``getAccountInfo`` JSON-RPC method. The caller receives
        the inner ``value`` dict (with ``data``, ``owner``, ``lamports``,
        ...) rather than the outer ``{"context": ..., "value": ...}``
        envelope.
        """

        params: list[Any] = [
            pubkey_b58,
            {"encoding": encoding, "commitment": self._commitment},
        ]
        result = await self._call("getAccountInfo", params)
        if not isinstance(result, dict):
            return None
        value = result.get("value")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise UpstreamError(
                "Solana RPC getAccountInfo returned non-dict value.",
                details={"upstream": "solana_rpc", "value_type": type(value).__name__},
            )
        return value

    async def get_multiple_accounts(
        self,
        pubkeys_b58: list[str],
        encoding: str = "base64",
    ) -> list[dict[str, Any] | None]:
        """Return account data for a batch of pubkeys (positional ordering).

        Wraps the ``getMultipleAccounts`` JSON-RPC method. Missing accounts
        appear as ``None`` at the matching index.
        """

        params: list[Any] = [
            pubkeys_b58,
            {"encoding": encoding, "commitment": self._commitment},
        ]
        result = await self._call("getMultipleAccounts", params)
        if not isinstance(result, dict):
            return [None for _ in pubkeys_b58]
        values = result.get("value") or []
        if not isinstance(values, list):
            raise UpstreamError(
                "Solana RPC getMultipleAccounts returned non-list value.",
                details={"upstream": "solana_rpc", "value_type": type(values).__name__},
            )
        normalized: list[dict[str, Any] | None] = []
        for entry in values:
            if entry is None:
                normalized.append(None)
            elif isinstance(entry, dict):
                normalized.append(entry)
            else:
                normalized.append(None)
        return normalized

    async def get_program_accounts(
        self,
        program_id_b58: str,
        filters: list[dict[str, Any]] | None = None,
        encoding: str = "base64",
    ) -> list[dict[str, Any]]:
        """List accounts owned by ``program_id_b58`` with optional filters.

        Wraps the ``getProgramAccounts`` JSON-RPC method. Returns the raw
        ``[{"pubkey": ..., "account": {...}}, ...]`` list — empty if no
        account matches.
        """

        config: dict[str, Any] = {"encoding": encoding, "commitment": self._commitment}
        if filters:
            config["filters"] = filters
        params: list[Any] = [program_id_b58, config]
        result = await self._call("getProgramAccounts", params)
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    async def get_recent_blockhash(self) -> dict[str, Any]:
        """Return the latest blockhash + last-valid block height.

        Wraps the modern ``getLatestBlockhash`` JSON-RPC method (the legacy
        ``getRecentBlockhash`` was removed from Solana 1.9+). The returned
        shape is ``{"blockhash": <str>, "lastValidBlockHeight": <int>}``.
        """

        params: list[Any] = [{"commitment": self._commitment}]
        result = await self._call("getLatestBlockhash", params)
        if not isinstance(result, dict):
            raise UpstreamError(
                "Solana RPC getLatestBlockhash returned non-dict result.",
                details={"upstream": "solana_rpc", "result_type": type(result).__name__},
            )
        value = result.get("value")
        if not isinstance(value, dict):
            raise UpstreamError(
                "Solana RPC getLatestBlockhash returned non-dict value.",
                details={"upstream": "solana_rpc", "value_type": type(value).__name__},
            )
        blockhash = value.get("blockhash")
        last_valid = value.get("lastValidBlockHeight")
        if not isinstance(blockhash, str) or not isinstance(last_valid, int):
            raise UpstreamError(
                "Solana RPC getLatestBlockhash returned malformed value.",
                details={"upstream": "solana_rpc", "value": value},
            )
        return {"blockhash": blockhash, "lastValidBlockHeight": last_valid}

    # ------------------------------------------------------------------
    # Public API — write methods
    # ------------------------------------------------------------------
    async def send_transaction(
        self,
        signed_tx_b64: str,
        skip_preflight: bool = False,
    ) -> str:
        """Submit a base64-encoded signed transaction.

        Wraps the ``sendTransaction`` JSON-RPC method with
        ``encoding="base64"``. Returns the transaction signature as a
        base58 string.
        """

        params: list[Any] = [
            signed_tx_b64,
            {
                "encoding": "base64",
                "skipPreflight": skip_preflight,
                "preflightCommitment": self._commitment,
            },
        ]
        result = await self._call("sendTransaction", params)
        if not isinstance(result, str):
            raise UpstreamError(
                "Solana RPC sendTransaction returned non-string signature.",
                details={"upstream": "solana_rpc", "result_type": type(result).__name__},
            )
        return result


# Module-level singleton. Importers can either use this or instantiate their
# own (e.g. for tests with custom rpc_url).
_solana_rpc_client: SolanaRpcClient | None = None


def get_solana_rpc_client() -> SolanaRpcClient:
    """FastAPI dependency factory for the lazy Solana RPC singleton."""

    global _solana_rpc_client
    if _solana_rpc_client is None:
        _solana_rpc_client = SolanaRpcClient()
    return _solana_rpc_client
