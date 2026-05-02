"""Relayer registry + selection service.

Owns the ``db.relayers`` collection. Operators register their nodes via
``scripts/seed_relayers.py``; the running backend reads the same
collection to (1) advertise the network on the frontend and (2) pick the
best relayer for a given withdrawal. Live stats (24h jobs, 24h volume,
last-seen) are computed by joining against ``db.withdrawals`` so they
reflect actual on-chain activity rather than self-reported numbers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.exceptions import ServiceUnavailableError
from app.models.relayer import Relayer

logger = logging.getLogger(__name__)


# Mapping of frontend sort keys to (Mongo field, direction). Anything
# unknown falls back to uptime descending so the API never 400s on a
# typo — the frontend's only options are uptime/fee/ping/jobs.
_SORT_FIELDS: dict[str, tuple[str, int]] = {
    "uptime": ("uptime_pct", -1),
    "fee": ("fee_bps", 1),
    "ping": ("ping_ms", 1),
    "jobs": ("jobs_24h", -1),
}


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


def _from_doc(doc: dict[str, Any]) -> Relayer:
    clean = _strip_id(doc)
    for key in ("registered_at", "last_seen"):
        value = clean.get(key)
        if isinstance(value, str):
            clean[key] = datetime.fromisoformat(value)
    return Relayer(**clean)


def _to_doc(relayer: Relayer) -> dict[str, Any]:
    return relayer.model_dump()


class RelayerService:
    """Coordinates the ``db.relayers`` collection and live stats joins."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Registry mutations
    # ------------------------------------------------------------------
    async def upsert(self, relayer: Relayer) -> Relayer:
        """Insert or update a relayer keyed by ``relayer_id``.

        The seeded ``id`` (uuid) is preserved on insert; existing
        ``id`` / ``registered_at`` are kept on update so callers don't
        clobber long-lived identifiers.
        """

        existing = await self._db.relayers.find_one({"relayer_id": relayer.relayer_id})
        doc = _to_doc(relayer)
        if existing:
            doc["id"] = existing.get("id", doc["id"])
            doc["registered_at"] = existing.get("registered_at", doc["registered_at"])
        await self._db.relayers.update_one(
            {"relayer_id": relayer.relayer_id},
            {"$set": doc},
            upsert=True,
        )
        logger.info(
            "relayer.upsert id=%s pubkey=%s region=%s",
            relayer.relayer_id,
            relayer.pubkey,
            relayer.region,
        )
        return _from_doc(doc)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    async def list_active(self, sort: str = "uptime", limit: int = 50) -> list[Relayer]:
        """Return registered relayers sorted by the requested key.

        Defaults to ``uptime`` descending — the order shown by the
        frontend leaderboard. Unknown sort keys silently fall back to
        the same default.
        """

        field, direction = _SORT_FIELDS.get(sort, _SORT_FIELDS["uptime"])
        cursor = self._db.relayers.find().sort(field, direction).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [_from_doc(doc) for doc in docs]

    async def get(self, relayer_id: str) -> Relayer | None:
        """Return a single relayer by ``relayer_id`` or ``None``."""

        doc = await self._db.relayers.find_one({"relayer_id": relayer_id})
        if not doc:
            return None
        return _from_doc(doc)

    async def stats(self, relayer_id: str) -> dict[str, Any]:
        """Compute live stats for ``relayer_id``.

        ``jobs_24h`` and ``volume_24h_lamports`` are joined from
        ``db.withdrawals`` so the dashboard reflects real activity.
        ``uptime_pct`` and ``ping_ms_avg`` are still operator-reported
        — there's no way to measure those server-side without a probe
        network, which is out of scope for the hackathon build.
        """

        relayer = await self.get(relayer_id)
        if not relayer:
            return {
                "relayer_id": relayer_id,
                "jobs_24h": 0,
                "volume_24h_lamports": 0,
                "last_seen": None,
                "uptime_pct": 0.0,
                "ping_ms_avg": 0,
            }

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        cursor = self._db.withdrawals.aggregate(
            [
                {"$match": {"relayer_id": relayer_id, "created_at": {"$gte": since}}},
                {
                    "$group": {
                        "_id": "$relayer_id",
                        "jobs": {"$sum": 1},
                        "volume": {"$sum": "$amount"},
                        "last_seen": {"$max": "$created_at"},
                    }
                },
            ]
        )
        jobs = 0
        volume = 0
        last_seen: datetime | None = relayer.last_seen
        async for entry in cursor:
            jobs = int(entry.get("jobs", 0))
            volume = int(entry.get("volume", 0))
            entry_last = entry.get("last_seen")
            if isinstance(entry_last, datetime):
                last_seen = entry_last

        return {
            "relayer_id": relayer_id,
            "jobs_24h": jobs,
            "volume_24h_lamports": volume,
            "last_seen": last_seen,
            "uptime_pct": relayer.uptime_pct,
            "ping_ms_avg": relayer.ping_ms,
        }

    async def pick_best(self, token: str | None = None) -> Relayer:
        """Return the best relayer for a withdrawal request.

        For now this is just "highest uptime" — once we have probe data
        we can also weight by region proximity to the recipient and the
        fee-vs-volume curve. ``token`` is accepted now so callers don't
        need a signature change later. Raises
        :class:`ServiceUnavailableError` when the registry is empty.
        """

        del token  # reserved for future routing logic
        candidates = await self.list_active(sort="uptime", limit=1)
        if not candidates:
            raise ServiceUnavailableError(
                "No relayers registered.",
                details={"hint": "Run scripts/seed_relayers.py to bootstrap."},
            )
        return candidates[0]
