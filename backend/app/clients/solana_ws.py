"""Async WebSocket client for the Solana JSON-RPC pubsub interface.

The client wraps :func:`solana.rpc.websocket_api.connect` from ``solana-py``
(already in ``requirements.txt`` via ``solana>=0.34``) and exposes two
high-level async iterators that the BagsVault indexer consumes:

* :meth:`SolanaWsClient.subscribe_account` — yields every notification
  for a single account PDA (used by the Merkle-tree state subscription).
* :meth:`SolanaWsClient.subscribe_logs` — yields notifications matching
  the requested logs filter (``all``, ``allWithVotes`` or ``mentions``).

Both helpers reconnect with exponential backoff (capped at 30s) on
transient WebSocket failures so a flaky node doesn't take the indexer
down. Only an empty/invalid URL raises
:class:`app.exceptions.ServiceUnavailableError`; transient drops just log
and retry.

Each yielded notification is a plain ``dict`` (parsed from the underlying
``solders`` typed object via :meth:`to_json`) so callers can stay
SDK-agnostic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import TracebackType
from typing import Any, AsyncIterator, Type

from solders.pubkey import Pubkey
from solders.rpc.config import RpcTransactionLogsFilter, RpcTransactionLogsFilterMentions

from app.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


# Backoff bounds for the reconnect loop. Initial delay doubles every
# failed attempt up to ``_RECONNECT_MAX_BACKOFF`` seconds.
_RECONNECT_INITIAL_BACKOFF = 1.0
_RECONNECT_MAX_BACKOFF = 30.0


class SolanaWsClient:
    """Thin async wrapper around the Solana pubsub WebSocket API.

    The instance is reusable for the lifetime of the process; each
    ``subscribe_*`` call opens its own underlying ws connection (matching
    the pattern of ``solana-py``'s ``connect`` async context manager).
    """

    def __init__(self, ws_url: str) -> None:
        if not ws_url or not (ws_url.startswith("ws://") or ws_url.startswith("wss://")):
            raise ServiceUnavailableError(
                "Solana WebSocket URL is not configured.",
                details={"ws_url": ws_url},
            )
        self._ws_url = ws_url

    # ------------------------------------------------------------------
    # Async-context-manager sugar (no shared connection — provided so
    # callers can treat the client uniformly with the RPC client).
    # ------------------------------------------------------------------
    async def __aenter__(self) -> "SolanaWsClient":
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def close(self) -> None:
        """No-op kept for API symmetry with ``SolanaRpcClient.aclose()``."""

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_msg(msg: Any) -> list[Any]:
        """Coerce a ws ``recv`` payload into a flat list of items.

        ``solana-py`` historically returned ``list[Notification]`` per
        recv, but tests / older versions sometimes deliver a single
        notification. Accepting both keeps the call-sites trivial.
        """

        if isinstance(msg, list):
            return msg
        return [msg]

    @staticmethod
    def _to_dict(message: Any) -> dict[str, Any]:
        """Convert a ``solders`` notification object into a plain dict.

        Falls back to the object's repr if JSON serialisation isn't
        available so callers always get a non-None mapping.
        """

        to_json = getattr(message, "to_json", None)
        if callable(to_json):
            try:
                payload = to_json()
                parsed = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, TypeError):
                pass
        return {"raw": repr(message)}

    @staticmethod
    def _logs_filter(
        kind: str, value: str | None
    ) -> RpcTransactionLogsFilter | RpcTransactionLogsFilterMentions:
        """Map ``("all" | "allWithVotes" | "mentions", pubkey?)`` to solders enum."""

        normalized = kind.lower()
        if normalized == "all":
            return RpcTransactionLogsFilter.All
        if normalized in {"allwithvotes", "all_with_votes"}:
            return RpcTransactionLogsFilter.AllWithVotes
        if normalized == "mentions":
            if not value:
                raise ServiceUnavailableError(
                    "logs_subscribe filter='mentions' requires a pubkey value.",
                    details={"filter_kind": kind},
                )
            try:
                return RpcTransactionLogsFilterMentions(Pubkey.from_string(value))
            except Exception as exc:  # noqa: BLE001 — surface as 503
                raise ServiceUnavailableError(
                    "logs_subscribe mentions filter received an invalid pubkey.",
                    details={"pubkey": value, "error": str(exc)},
                ) from exc
        raise ServiceUnavailableError(
            "Unknown logs filter kind.",
            details={"filter_kind": kind, "supported": ["all", "allWithVotes", "mentions"]},
        )

    async def _reconnect_loop(
        self,
        subscribe: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run ``subscribe`` (an async generator factory) with exponential backoff."""

        backoff = _RECONNECT_INITIAL_BACKOFF
        while True:
            try:
                async for item in subscribe():
                    backoff = _RECONNECT_INITIAL_BACKOFF
                    yield item
                # Generator returned cleanly — server-side close. Reconnect.
                logger.info("Solana WS subscription closed cleanly; reconnecting in %.1fs", backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — log and retry transient errors
                logger.warning(
                    "Solana WS subscription error (will retry in %.1fs): %s",
                    backoff,
                    exc,
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_BACKOFF)

    # ------------------------------------------------------------------
    # Public subscription API
    # ------------------------------------------------------------------
    async def subscribe_account(
        self,
        pubkey_b58: str,
        encoding: str = "base64",
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``accountNotification`` payloads for ``pubkey_b58``.

        Each yielded value is the parsed solders notification serialised
        to a plain dict (so callers don't depend on the SDK's typed
        responses). The iterator runs forever — wrap in
        ``async for ... :`` and ``break`` when you want to stop.
        """

        try:
            pubkey = Pubkey.from_string(pubkey_b58)
        except Exception as exc:  # noqa: BLE001 — surface as 503
            raise ServiceUnavailableError(
                "Invalid pubkey supplied to subscribe_account.",
                details={"pubkey": pubkey_b58, "error": str(exc)},
            ) from exc

        async def _open() -> AsyncIterator[dict[str, Any]]:
            # Imported lazily so test environments without a real network
            # can monkeypatch ``connect`` without paying the import cost.
            from solana.rpc.websocket_api import connect

            async with connect(self._ws_url) as ws:
                await ws.account_subscribe(pubkey, encoding=encoding)
                async for msg in ws:
                    if not msg:
                        continue
                    # Each ws yield is a list of notifications/results.
                    for item in self._normalize_msg(msg):
                        yield self._to_dict(item)

        async for payload in self._reconnect_loop(_open):
            yield payload

    async def subscribe_logs(
        self,
        filter_kind: str = "all",
        filter_value: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``logsNotification`` payloads.

        ``filter_kind`` is one of ``"all"``, ``"allWithVotes"`` or
        ``"mentions"``. When ``"mentions"`` is requested ``filter_value``
        must be a base58 pubkey.
        """

        log_filter = self._logs_filter(filter_kind, filter_value)

        async def _open() -> AsyncIterator[dict[str, Any]]:
            from solana.rpc.websocket_api import connect

            async with connect(self._ws_url) as ws:
                await ws.logs_subscribe(log_filter)
                async for msg in ws:
                    if not msg:
                        continue
                    for item in self._normalize_msg(msg):
                        yield self._to_dict(item)

        async for payload in self._reconnect_loop(_open):
            yield payload
