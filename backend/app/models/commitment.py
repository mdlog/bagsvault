"""Commitment domain model.

A commitment is the hashed deposit record that joins the BagsVault
anonymity set. The frontend submits one per deposit; the backend
verifies the matching on-chain transaction and persists the commitment
to ``db.commitments`` so anonymity-set + recent-deposits views can be
served without re-walking the chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class Commitment(BaseModel):
    """Persisted commitment record."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    commitment: str = Field(description="Full hex-encoded commitment hash")
    merkle_index: int = Field(ge=0, description="Sequential index in the Merkle tree")
    amount: int = Field(ge=0, description="Deposited amount in lamports / smallest unit")
    token: str = Field(description="Mint address or 'SOL' for native lamports")
    tx_signature: str = Field(description="Base58 signature of the on-chain deposit tx")
    creator_wallet: str | None = Field(
        default=None, description="Optional creator pubkey for creator-fee deposits"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommitmentCreate(BaseModel):
    """Request body for ``POST /api/deposits``.

    ``id``, ``merkle_index``, and ``created_at`` are server-assigned and
    omitted from the inbound payload.
    """

    model_config = ConfigDict(extra="ignore")

    commitment: str = Field(min_length=1, description="Full hex-encoded commitment hash")
    amount: int = Field(ge=0, description="Deposited amount in lamports / smallest unit")
    token: str = Field(min_length=1, description="Mint address or 'SOL' for native lamports")
    tx_signature: str = Field(min_length=1, description="Base58 deposit tx signature")
    creator_wallet: str | None = Field(default=None, description="Optional creator pubkey")
