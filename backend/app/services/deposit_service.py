"""Deposit service: confirms on-chain deposit txs and persists commitments.

The deposit flow:

1. The client pre-screens the wallet via ``/api/compliance/scan`` and
   broadcasts the on-chain deposit transaction (which includes the
   commitment hash as part of the program instruction data).
2. The client POSTs ``{commitment, tx_signature, amount, token, ...}``
   to ``/api/deposits``.
3. This service verifies the transaction landed (and did not fail), then
   inserts a ``Commitment`` row keyed by the commitment hash.
4. The service kicks the Merkle indexer best-effort so the next reader
   sees the freshly-mined root.

Idempotency: a re-POST with the same ``commitment`` returns the cached
record. A re-POST with a different ``tx_signature`` for the same
commitment is rejected with :class:`ConflictError`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.clients.solana_rpc import SolanaRpcClient
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.commitment import Commitment
from app.services.merkle_indexer import MerkleIndexer

logger = logging.getLogger(__name__)

# Hex-shortening for anonymized recent-deposits view.
_HASH_PREFIX_LEN = 4
_HASH_SUFFIX_LEN = 4


class DepositService:
    """Coordinates Solana RPC verification + the local commitments cache."""

    def __init__(
        self,
        rpc: SolanaRpcClient,
        db: AsyncIOMotorDatabase,
        merkle: MerkleIndexer,
    ) -> None:
        self._rpc = rpc
        self._db = db
        self._merkle = merkle

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def register(
        self,
        *,
        commitment: str,
        amount: int,
        token: str,
        tx_signature: str,
        creator_wallet: str | None,
    ) -> Commitment:
        """Verify ``tx_signature`` then insert the commitment row.

        Raises:
            ConflictError: same commitment recorded with a different signature.
            NotFoundError: transaction not visible on the network yet.
            ValidationError: transaction landed but has a non-empty error meta.
        """

        # 1. Idempotency check.
        existing_doc = await self._db.commitments.find_one({"commitment": commitment}, {"_id": 0})
        if existing_doc is not None:
            existing = self._from_doc(existing_doc)
            if existing.tx_signature == tx_signature:
                logger.info(
                    "deposits.register hit cache commitment=%s idx=%d",
                    commitment[:12],
                    existing.merkle_index,
                )
                return existing
            raise ConflictError(
                "Commitment already recorded with a different transaction signature.",
                details={
                    "commitment": commitment,
                    "existing_tx_signature": existing.tx_signature,
                    "submitted_tx_signature": tx_signature,
                },
            )

        # 2. On-chain confirmation.
        tx = await self._rpc.get_transaction(tx_signature)
        if tx is None:
            raise NotFoundError(
                "Transaction not yet confirmed on chain.",
                details={"tx_signature": tx_signature},
            )

        meta = tx.get("meta")
        if isinstance(meta, dict) and meta.get("err") is not None:
            raise ValidationError(
                "Deposit transaction failed on chain.",
                details={"tx_signature": tx_signature, "err": meta.get("err")},
            )

        # 3. Allocate sequential merkle index. Phase 3 may swap this for a
        #    read of the on-chain commitment_count once the program is live.
        merkle_index = await self._db.commitments.count_documents({})

        record = Commitment(
            commitment=commitment,
            merkle_index=merkle_index,
            amount=amount,
            token=token,
            tx_signature=tx_signature,
            creator_wallet=creator_wallet,
        )

        try:
            await self._db.commitments.insert_one(record.model_dump())
        except DuplicateKeyError:
            # Race: another caller inserted between our find_one and insert.
            # Re-fetch and either return the cached row (matching sig) or
            # raise ConflictError (mismatched sig).
            cached_doc = await self._db.commitments.find_one({"commitment": commitment}, {"_id": 0})
            if cached_doc is None:
                raise
            cached = self._from_doc(cached_doc)
            if cached.tx_signature == tx_signature:
                return cached
            raise ConflictError(
                "Commitment already recorded with a different transaction signature.",
                details={
                    "commitment": commitment,
                    "existing_tx_signature": cached.tx_signature,
                    "submitted_tx_signature": tx_signature,
                },
            )

        # 4. Kick the indexer best-effort.
        try:
            await self._merkle.sync_now()
        except Exception:  # noqa: BLE001 — best-effort, do not block deposits
            logger.exception("merkle.sync_now after deposit failed; continuing")

        logger.info(
            "deposits.register inserted commitment=%s idx=%d token=%s amount=%d",
            commitment[:12],
            merkle_index,
            token,
            amount,
        )
        return record

    async def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the ``limit`` most recent deposits, anonymized.

        Strips ``creator_wallet`` and ``tx_signature`` and replaces the full
        commitment hash with a short fingerprint of the form ``7a3f…c9e1``.
        """

        cursor = self._db.commitments.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
        out: list[dict[str, Any]] = []
        async for doc in cursor:
            commitment = str(doc.get("commitment", ""))
            out.append(
                {
                    "commitment_hash_short": self._shorten(commitment),
                    "amount": int(doc.get("amount", 0)),
                    "token": doc.get("token", ""),
                    "merkle_index": int(doc.get("merkle_index", 0)),
                    "indexed_at": doc.get("created_at"),
                }
            )
        return out

    async def get_anonymity_set(self) -> dict[str, Any]:
        """Aggregate count + current root for the landing/withdraw views.

        Never raises on missing program ID — falls back to the all-zeroes
        empty-tree root so the frontend always renders a number.
        """

        count = await self._db.commitments.count_documents({})
        current = await self._merkle.get_current_root()
        if current is not None:
            return {
                "count": count,
                "current_root": current.root,
                "updated_at": current.indexed_at,
                "source": current.source,
            }
        return {
            "count": count,
            "current_root": "0" * 64,
            "updated_at": datetime.now(timezone.utc),
            "source": "fallback",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _shorten(commitment: str) -> str:
        clean = commitment.removeprefix("0x")
        if len(clean) <= _HASH_PREFIX_LEN + _HASH_SUFFIX_LEN:
            return clean
        return f"{clean[:_HASH_PREFIX_LEN]}…{clean[-_HASH_SUFFIX_LEN:]}"

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> Commitment:
        clean = {k: v for k, v in doc.items() if k != "_id"}
        if isinstance(clean.get("created_at"), str):
            clean["created_at"] = datetime.fromisoformat(clean["created_at"])
        return Commitment(**clean)
