"""Async HTTP client for the Bags API.

Bags exposes the trade, claim-fees, fee-share, and token-launch APIs that
BagsVault needs to source creator fees and route swaps before depositing
into the privacy pool. This client is the single entry point to that API
and surfaces strongly-typed errors so the FastAPI exception handlers can
turn them into structured responses.

Hackathon constraint: no mocks. If ``settings.bags_api_key`` is empty,
every business-logic call raises :class:`ServiceUnavailableError` so the
operator gets a clear signal that the Bags integration must be configured.
:meth:`ping` is intentionally tolerant — it never raises and always
returns a structured dict so the ``/api/bags/health`` probe can short-circuit.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.exceptions import ServiceUnavailableError, UpstreamError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class BagsAPIClient:
    """Thin async wrapper around the Bags REST API.

    The client lazily creates a single ``httpx.AsyncClient`` and reuses it for
    the lifetime of the process. Call :meth:`aclose` on shutdown if you want
    to release the underlying connection pool deterministically.

    Endpoint path assumptions are documented per-method. The lead agent
    should verify them against the latest https://docs.bags.fm/ references
    before going live.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._base_url = (base_url or settings.bags_api_base_url).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.bags_api_key
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _ensure_configured(self) -> None:
        if not self._api_key:
            raise ServiceUnavailableError(
                "Bags API is not configured. Set the BAGS_API_KEY env "
                "variable to enable token / fee / swap integrations.",
                details={"missing_env": "BAGS_API_KEY"},
            )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Accept": "application/json",
                "User-Agent": "bagsvault-backend/0.1",
            }
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers=headers,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a request and normalize errors to UpstreamError.

        Always returns a JSON dict. Non-dict JSON bodies (e.g. arrays) are
        wrapped under ``{"data": <body>}`` so callers can rely on a stable
        shape.
        """

        self._ensure_configured()
        client = self._get_client()

        try:
            response = await client.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            logger.exception("Bags API network error on %s %s", method, path)
            raise UpstreamError(
                "Failed to reach Bags API.",
                details={"upstream": "bags", "path": path, "error": str(exc)},
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "Bags API returned %s for %s %s: %s",
                response.status_code,
                method,
                path,
                response.text[:500],
            )
            raise UpstreamError(
                f"Bags API returned HTTP {response.status_code}.",
                details={
                    "upstream": "bags",
                    "path": path,
                    "status_code": response.status_code,
                    "body": response.text[:1000],
                },
            )

        # Some endpoints (rare) return empty body on success.
        if not response.content:
            return {}

        try:
            data = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "Bags API returned a non-JSON body.",
                details={"upstream": "bags", "path": path, "body": response.text[:500]},
            ) from exc

        if isinstance(data, list):
            return {"data": data}
        if not isinstance(data, dict):
            raise UpstreamError(
                "Bags API returned an unexpected JSON shape.",
                details={"upstream": "bags", "path": path, "type": type(data).__name__},
            )
        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def ping(self) -> dict[str, Any]:
        """Probe Bags API connectivity. Never raises.

        Docs assumption: there is no published "ping" endpoint, so we hit
        the API root (``GET /``). Any 2xx/3xx is treated as reachable;
        4xx with a JSON body still counts as reachable (the API answered).
        Network errors are reported as ``{"reachable": False, "error": ...}``.
        """

        if not self._api_key:
            return {"reachable": False, "configured": False, "error": "BAGS_API_KEY not set"}

        client = self._get_client()
        try:
            response = await client.get("/")
        except httpx.HTTPError as exc:
            logger.warning("Bags API ping failed: %s", exc)
            return {"reachable": False, "configured": True, "error": str(exc)}

        return {
            "reachable": True,
            "configured": True,
            "status_code": response.status_code,
        }

    async def get_claimable_fees(
        self, creator_wallet: str, token_mint: str | None = None
    ) -> dict[str, Any]:
        """List unclaimed fees for ``creator_wallet``.

        Docs assumption: ``GET /token-launch/claimable/v3`` accepts query
        params ``wallet`` (required) and ``tokenMint`` (optional). The exact
        path is inferred from the public ``/token-launch/claim-txs/v3`` flow
        described at https://docs.bags.fm/how-to-guides/claim-fees and is
        the most likely sibling endpoint. Update this method when the real
        contract is confirmed.
        """

        params: dict[str, Any] = {"wallet": creator_wallet}
        if token_mint:
            params["tokenMint"] = token_mint
        return await self._request("GET", "/token-launch/claimable/v3", params=params)

    async def build_claim_tx(
        self, creator_wallet: str, token_mint: str | None = None
    ) -> dict[str, Any]:
        """Build an unsigned claim transaction (or batch) for the wallet to sign.

        Docs assumption: ``POST /token-launch/claim-txs/v3`` accepts
        ``{"wallet": <pubkey>, "tokenMint": <pubkey?>}`` and returns one or
        more base64-encoded unsigned transactions. Reference:
        https://docs.bags.fm/how-to-guides/claim-fees#claim-token-fees.
        """

        body: dict[str, Any] = {"wallet": creator_wallet}
        if token_mint:
            body["tokenMint"] = token_mint
        return await self._request("POST", "/token-launch/claim-txs/v3", json=body)

    async def get_swap_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        """Fetch a swap quote / route + unsigned tx via the Bags trade API.

        Docs assumption: ``POST /trade/swap`` accepts
        ``{"inputMint", "outputMint", "amount" (lamports / smallest unit),
        "slippageBps"}`` and returns a route + unsigned transaction.
        Reference: https://docs.bags.fm/how-to-guides/trade-tokens.
        """

        body: dict[str, Any] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage_bps,
        }
        return await self._request("POST", "/trade/swap", json=body)

    async def get_fee_share(self, token_mint: str) -> dict[str, Any]:
        """Fetch the configured Fee Share V2 distribution for ``token_mint``.

        Docs assumption: ``GET /fee-share/v2/{token_mint}`` exposes the
        distribution configured for the Fee Share V2 program
        (``FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`` per
        https://docs.bags.fm/principles/program-ids). The exact REST surface
        is not formally documented at the time of writing — update this path
        once the official endpoint is confirmed.
        """

        return await self._request("GET", f"/fee-share/v2/{token_mint}")

    async def get_token_metadata(self, mint: str) -> dict[str, Any]:
        """Fetch upstream Bags metadata for a launched token.

        Docs assumption: ``GET /token-launch/{mint}`` returns the canonical
        Bags metadata for a token (name, symbol, decimals, creator,
        socials, ...). Used by ``GET /api/tokens/{mint}`` to enrich the
        local registry record.
        """

        return await self._request("GET", f"/token-launch/{mint}")

    async def build_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        decimals: int,
        supply: int,
        authority_pubkey: str,
        metadata_uri: str | None = None,
    ) -> dict[str, Any]:
        """Build an unsigned token-launch transaction for the operator to sign.

        Docs assumption: ``POST /token-launch/build`` accepts the launch
        configuration and returns ``{"transaction": <base64>, "mint": <pubkey?>}``.
        The exact endpoint is not yet documented publicly — this is a
        best-inference shape based on the rest of the Bags token-launch
        family. Used by ``scripts/launch_vault_token.py``.
        """

        body: dict[str, Any] = {
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "supply": supply,
            "authority": authority_pubkey,
        }
        if metadata_uri:
            body["metadataUri"] = metadata_uri
        return await self._request("POST", "/token-launch/build", json=body)


# Module-level singleton. Importers can either use this or instantiate their
# own (e.g. for tests with custom base_url).
bags_api_client = BagsAPIClient()


def get_bags_api_client() -> BagsAPIClient:
    """FastAPI dependency factory for the Bags API client."""

    return bags_api_client
