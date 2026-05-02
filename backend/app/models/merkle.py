"""Merkle-root cache model.

Each row represents an observed root of the BagsVault on-chain Merkle
tree. The indexer (:class:`app.services.merkle_indexer.MerkleIndexer`)
upserts a new row whenever it observes a root different from the most
recent one. The frontend reads the cache via ``GET /api/merkle/root``
and ``GET /api/anonymity-set`` so the protocol page can render without
hitting the RPC on every request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RootSource = Literal["indexed", "fallback"]


class MerkleRoot(BaseModel):
    """A snapshot of the Merkle-tree root at a point in time."""

    model_config = ConfigDict(extra="ignore")

    root: str = Field(description="Hex-encoded 32-byte root")
    commitment_count: int = Field(
        ge=0, description="On-chain commitment count at the time of indexing"
    )
    block_height: int | None = Field(
        default=None, description="Slot / block height the root was observed at"
    )
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: RootSource = Field(
        default="indexed",
        description="`indexed` if read from the program account, `fallback` otherwise",
    )
