"""Relayer registry models.

A relayer is an off-chain operator that pays Solana gas in exchange for a
fee taken from the withdrawn amount. The registry powers two screens in
the frontend (relayer selection during withdrawal and the live operator
leaderboard) so the model carries the same denormalized stats those views
display: fee in basis points, operator-reported ``ping_ms`` and
``uptime_pct`` plus cached ``jobs_24h`` / ``volume_24h_lamports``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class Relayer(BaseModel):
    """Persisted relayer registry row stored in ``db.relayers``.

    ``relayer_id`` and ``pubkey`` both carry unique indexes — see
    :func:`app.database.ensure_indexes`.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    relayer_id: str
    name: str
    operator: str
    pubkey: str
    region: str
    fee_bps: int = Field(ge=0, le=10_000)
    ping_ms: int = Field(ge=0)
    uptime_pct: float = Field(ge=0.0, le=100.0)
    jobs_24h: int = Field(default=0, ge=0)
    volume_24h_lamports: int = Field(default=0, ge=0)
    last_seen: datetime | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RelayerRegister(BaseModel):
    """Operator-supplied fields for ``RelayerService.upsert``."""

    model_config = ConfigDict(extra="ignore")

    relayer_id: str
    name: str
    operator: str
    pubkey: str
    region: str
    fee_bps: int = Field(ge=0, le=10_000)
    ping_ms: int = Field(ge=0)
    uptime_pct: float = Field(ge=0.0, le=100.0)
