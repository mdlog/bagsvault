"""Creator domain model.

A creator is a Solana wallet that has registered (or will register) one or
more project tokens with BagsVault. Stored in ``db.creators`` keyed by
``wallet`` (unique index defined in :func:`app.database.ensure_indexes`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class Creator(BaseModel):
    """Persisted creator record."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wallet: str
    display_name: str | None = None
    tokens: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreatorRegister(BaseModel):
    """Request body for registering / updating a creator profile."""

    model_config = ConfigDict(extra="ignore")

    wallet: str
    display_name: str | None = None
