"""Async HTTP client for the Range Risk API.

Range exposes wallet risk-scoring endpoints used by BagsVault to gate every
deposit against AML/sanctions/illicit-flow signals. This client speaks the
public Range Risk API directly via httpx and surfaces strongly-typed errors
that the FastAPI exception handlers can turn into structured responses.

Hackathon constraint: no mocks. If ``settings.range_api_key`` is empty, every
call raises :class:`ServiceUnavailableError` so the operator gets a clear
signal that the Range integration must be configured.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.exceptions import ServiceUnavailableError, UpstreamError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class RangeRiskClient:
    """Thin async wrapper around the Range Risk REST API.

    The client lazily creates a single ``httpx.AsyncClient`` and reuses it for
    the lifetime of the process. Call :meth:`aclose` on shutdown if you want
    to release the underlying connection pool deterministically.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._base_url = (base_url or settings.range_api_base_url).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.range_api_key
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _ensure_configured(self) -> None:
        if not self._api_key:
            raise ServiceUnavailableError(
                "Range Risk API is not configured. Set the RANGE_API_KEY env "
                "variable to enable wallet risk scoring.",
                details={"missing_env": "RANGE_API_KEY"},
            )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
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
    # Public API
    # ------------------------------------------------------------------
    async def scan_address(self, address: str) -> dict[str, Any]:
        """Score a Solana wallet via Range Risk and return the raw payload.

        Assumption: Range exposes a generic risk-score endpoint at
        ``POST {base}/v1/risk/score`` that accepts ``{"chain": "solana",
        "address": <pubkey>}``. The exact contract isn't fully public, so the
        service layer normalizes whatever shape comes back via
        :meth:`RiskScan.from_range_response`. If the real endpoint differs,
        only this method needs to change.
        """

        self._ensure_configured()
        client = self._get_client()
        payload: dict[str, Any] = {"chain": "solana", "address": address}

        try:
            response = await client.post("/v1/risk/score", json=payload)
        except httpx.HTTPError as exc:
            logger.exception("Range Risk network error for address=%s", address)
            raise UpstreamError(
                "Failed to reach Range Risk API.",
                details={"upstream": "range", "error": str(exc)},
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "Range Risk returned %s for address=%s: %s",
                response.status_code,
                address,
                response.text[:500],
            )
            raise UpstreamError(
                f"Range Risk API returned HTTP {response.status_code}.",
                details={
                    "upstream": "range",
                    "status_code": response.status_code,
                    "body": response.text[:1000],
                },
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise UpstreamError(
                "Range Risk API returned a non-JSON body.",
                details={"upstream": "range", "body": response.text[:500]},
            ) from exc

        if not isinstance(data, dict):
            raise UpstreamError(
                "Range Risk API returned an unexpected JSON shape.",
                details={"upstream": "range", "type": type(data).__name__},
            )
        return data


# Module-level singleton. Importers can either use this or instantiate their
# own (e.g. for tests with custom base_url).
range_risk_client = RangeRiskClient()


def get_range_risk_client() -> RangeRiskClient:
    """FastAPI dependency factory for the Range Risk client."""

    return range_risk_client
