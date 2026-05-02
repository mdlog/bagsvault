"""Withdrawal domain models.

These cover both the wire shape posted to ``POST /api/withdrawals/relay``
and the persisted Mongo document stored in ``db.withdrawals``. The
nullifier hash is the unique key — a second withdrawal claiming the same
nullifier is the protocol's double-spend signal and the API rejects it
with HTTP 409.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class WithdrawalPublicInputs(BaseModel):
    """Public inputs the on-chain Groth16 verifier checks against the proof.

    ``amount`` is in lamports (or token base units when ``token`` is a mint).
    ``token`` is either ``"SOL"`` or a base58 SPL mint address.
    """

    model_config = ConfigDict(extra="ignore")

    root: str
    nullifier_hash: str
    recipient: str
    amount: int = Field(ge=0)
    token: str


class WithdrawalRelayRequest(BaseModel):
    """Body of ``POST /api/withdrawals/relay``."""

    model_config = ConfigDict(extra="ignore")

    proof: str
    public_inputs: WithdrawalPublicInputs


class Withdrawal(BaseModel):
    """Persisted withdrawal record stored in ``db.withdrawals``.

    ``nullifier_hash`` carries a unique index — see
    :func:`app.database.ensure_indexes`.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nullifier_hash: str
    recipient: str
    amount: int = Field(ge=0)
    token: str
    relayer_id: str
    tx_signature: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
