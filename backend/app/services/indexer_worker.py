"""Background asyncio task that keeps the Merkle-root cache fresh.

The worker runs inside the FastAPI process (spawned by ``app.main``'s
lifespan handler). It does **not** introduce a separate process or any
external scheduler — keeping the deployment story to "one container,
one Mongo".

Two operating modes are provided:

* :meth:`IndexerWorker.start` (default, polling) — calls
  :meth:`MerkleIndexer.sync_now` every ``interval_seconds``.
  Tradeoff: the cache lags by up to ``interval_seconds`` but the loop
  is dead simple and never holds a network socket open.
* :meth:`IndexerWorker.run_with_ws` (push) — uses
  :meth:`MerkleIndexer.subscribe_root_updates` so the cache updates the
  instant the on-chain account changes. Tradeoff: real-time but holds an
  open WebSocket and reconnects on disconnect.

The worker exposes ``last_sync_at`` / ``last_sync_error`` so an admin
endpoint can render a "Indexer healthy" badge without poking Mongo.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.services.merkle_indexer import MerkleIndexer

if TYPE_CHECKING:
    from app.clients.solana_ws import SolanaWsClient

logger = logging.getLogger(__name__)


class IndexerWorker:
    """Owns the lifecycle of a single background sync loop."""

    def __init__(self, indexer: MerkleIndexer, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._indexer = indexer
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._last_sync_at: datetime | None = None
        self._last_sync_error: str | None = None

    # ------------------------------------------------------------------
    # Status accessors
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        """Return ``True`` once :meth:`start` has spawned a live task."""

        return self._task is not None and not self._task.done()

    @property
    def last_sync_at(self) -> datetime | None:
        """UTC timestamp of the last successful ``sync_now`` (None if never)."""

        return self._last_sync_at

    @property
    def last_sync_error(self) -> str | None:
        """String-ified exception from the most recent failed tick (None if last tick ok)."""

        return self._last_sync_error

    # ------------------------------------------------------------------
    # Lifecycle (polling mode)
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Spawn the background sync loop. Idempotent."""

        if self.is_running:
            return
        logger.info("IndexerWorker starting (interval=%ds, mode=polling)", self._interval)
        self._task = asyncio.create_task(self._run_polling(), name="bagsvault-indexer-worker")

    async def stop(self) -> None:
        """Cancel the running task and wait for it to exit."""

        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 — log and swallow on shutdown
                logger.exception("IndexerWorker task raised on shutdown")
        self._task = None
        logger.info("IndexerWorker stopped")

    async def _tick(self) -> None:
        """Run a single sync iteration and record success/failure metadata."""

        try:
            await self._indexer.sync_now()
        except Exception as exc:  # noqa: BLE001 — never break the loop on transient errors
            self._last_sync_error = str(exc)
            logger.exception("IndexerWorker.sync_now raised: %s", exc)
        else:
            self._last_sync_at = datetime.now(timezone.utc)
            self._last_sync_error = None

    async def _run_polling(self) -> None:
        """Internal loop body for polling mode."""

        try:
            while True:
                await self._tick()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("IndexerWorker polling loop cancelled — exiting cleanly.")
            raise

    # ------------------------------------------------------------------
    # Optional WebSocket mode
    # ------------------------------------------------------------------
    async def run_with_ws(self, ws: "SolanaWsClient") -> None:
        """Real-time alternative to the polling loop.

        This blocks forever, yielding to ``await`` only on the underlying
        WebSocket recv. Callers should run it in a dedicated task and
        cancel it on shutdown.

        Tradeoff vs polling:

        * **Latency**: ws push delivers each new root within network RTT,
          polling lags up to ``interval_seconds``.
        * **Resource cost**: ws holds an open socket and reconnects on
          disconnect; polling fires a single short HTTP request per
          interval.
        """

        logger.info("IndexerWorker starting in WebSocket push mode")
        try:
            async for record in self._indexer.subscribe_root_updates(ws):
                self._last_sync_at = datetime.now(timezone.utc)
                self._last_sync_error = None
                logger.info(
                    "IndexerWorker captured new root via ws: root=%s count=%d",
                    record.root[:8],
                    record.commitment_count,
                )
        except asyncio.CancelledError:
            logger.info("IndexerWorker ws loop cancelled — exiting cleanly.")
            raise
        except Exception as exc:  # noqa: BLE001 — surface in last_sync_error
            self._last_sync_error = str(exc)
            logger.exception("IndexerWorker.run_with_ws raised: %s", exc)


# ----------------------------------------------------------------------
# Module-level singleton + factory
# ----------------------------------------------------------------------
_worker: IndexerWorker | None = None


def get_indexer_worker(
    indexer: MerkleIndexer | None = None,
    interval_seconds: int | None = None,
) -> IndexerWorker:
    """Lazily build and cache the process-wide :class:`IndexerWorker`.

    Both arguments are optional; they default to a freshly-built indexer
    bound to the singleton Mongo db + RPC client and the configured
    ``settings.indexer_interval_seconds``. Tests should call
    :func:`reset_indexer_worker` between cases.
    """

    global _worker
    if _worker is not None:
        return _worker

    # Imported lazily so test environments can patch out individual
    # dependencies without paying the cost of building them.
    from app.clients.anchor_decoder import get_anchor_decoder
    from app.clients.solana_rpc import get_solana_rpc_client
    from app.config import settings as _settings
    from app.database import db as _db

    if indexer is None:
        rpc = get_solana_rpc_client()
        decoder = get_anchor_decoder()
        indexer = MerkleIndexer(rpc=rpc, db=_db, decoder=decoder)
    interval = (
        interval_seconds if interval_seconds is not None else _settings.indexer_interval_seconds
    )
    _worker = IndexerWorker(indexer=indexer, interval_seconds=interval)
    return _worker


def reset_indexer_worker() -> None:
    """Test helper: drop the cached singleton."""

    global _worker
    _worker = None


def status_snapshot() -> dict[str, Any]:
    """Return a small JSON-serialisable status dict (handy for /health)."""

    if _worker is None:
        return {"running": False, "last_sync_at": None, "last_sync_error": None}
    return {
        "running": _worker.is_running,
        "last_sync_at": _worker.last_sync_at.isoformat() if _worker.last_sync_at else None,
        "last_sync_error": _worker.last_sync_error,
    }
