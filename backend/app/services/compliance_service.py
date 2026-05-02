"""Compliance service: orchestrates Range Risk scans + Mongo cache.

The Range Risk API is the single source of truth for whether a wallet is
allowed to deposit into the privacy pool. We persist normalized results into
``db.risk_scans`` (TTL 30 days, configured in :func:`app.database.ensure_indexes`)
so the dashboard and downstream gating logic can serve cached verdicts
without re-billing the upstream provider.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clients.range_risk import RangeRiskClient
from app.exceptions import NotFoundError
from app.models.risk_scan import RiskScan

logger = logging.getLogger(__name__)


class ComplianceService:
    """Coordinates Range Risk calls and the local risk_scans cache."""

    def __init__(self, db: AsyncIOMotorDatabase, client: RangeRiskClient) -> None:
        self._db = db
        self._client = client

    # ------------------------------------------------------------------
    # Mongo serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_doc(scan: RiskScan) -> dict[str, Any]:
        doc = scan.model_dump()
        # Mongo stores datetime natively; keep ISO for consistency in callers
        # that expect strings, but the TTL index requires a real BSON datetime.
        return doc

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> RiskScan:
        clean = {k: v for k, v in doc.items() if k != "_id"}
        if isinstance(clean.get("scanned_at"), str):
            clean["scanned_at"] = datetime.fromisoformat(clean["scanned_at"])
        return RiskScan(**clean)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def scan(self, address: str) -> RiskScan:
        """Run a fresh scan against Range Risk and upsert the cached result."""

        raw = await self._client.scan_address(address)
        scan = RiskScan.from_range_response(address, raw)
        await self._db.risk_scans.update_one(
            {"address": address},
            {"$set": self._to_doc(scan)},
            upsert=True,
        )
        logger.info(
            "compliance.scan address=%s verdict=%s score=%d",
            address,
            scan.verdict,
            scan.score,
        )
        return scan

    async def get_cached(self, address: str) -> RiskScan:
        """Return the cached scan for ``address`` or raise :class:`NotFoundError`."""

        doc = await self._db.risk_scans.find_one({"address": address}, {"_id": 0})
        if not doc:
            raise NotFoundError(
                f"No cached scan for address {address}.",
                details={"address": address},
            )
        return self._from_doc(doc)

    async def stats(self) -> dict[str, Any]:
        """Aggregate verdict counts for the Compliance dashboard.

        Returns the shape consumed by the frontend ``Compliance`` page —
        total scans, per-verdict counts, and a placeholder false-positive
        rate (we don't track human-overrides yet).
        """

        cursor = self._db.risk_scans.aggregate(
            [{"$group": {"_id": "$verdict", "count": {"$sum": 1}}}]
        )
        counts = {"APPROVE": 0, "REVIEW": 0, "BLOCK": 0}
        async for entry in cursor:
            verdict = entry.get("_id")
            if verdict in counts:
                counts[verdict] = int(entry.get("count", 0))

        total = sum(counts.values())
        return {
            "total_scans": total,
            "approvals": counts["APPROVE"],
            "reviews": counts["REVIEW"],
            "blocks": counts["BLOCK"],
            "false_positive_rate": 0.0,
        }
