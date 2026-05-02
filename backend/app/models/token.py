"""Project-token domain model.

Represents a token launched on Bags and registered with BagsVault. The
``$VAULT`` governance token is just a regular ``ProjectToken`` row with
``is_vault_token=True``. Stored in ``db.tokens`` keyed by ``mint`` (unique
index defined in :func:`app.database.ensure_indexes`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectToken(BaseModel):
    """Persisted project-token record."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mint: str
    creator_wallet: str
    symbol: str
    name: str
    decimals: int = 9
    metadata_uri: str | None = None
    is_vault_token: bool = False
    bags_metadata: dict[str, Any] | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TokenRegister(BaseModel):
    """Request body for ``POST /api/tokens/register``."""

    model_config = ConfigDict(extra="ignore")

    mint: str
    creator_wallet: str
    symbol: str
    name: str
    decimals: int = 9
    metadata_uri: str | None = None
