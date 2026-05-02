"""Merkle-root indexer service.

Best-effort cache of recent BagsVault Merkle-tree roots, populated by
reading the program's on-chain state account. The service is *safe to
call repeatedly* — duplicate roots are upserted as no-ops thanks to the
unique index on ``db.merkle_roots.root``.

The indexer is **not** scheduled here; calling code (``DepositService``
and Phase 3 background workers) decides when to invoke ``sync_now()``.
"""

from __future__ import annotations

import base64
import logging
import struct
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from solders.pubkey import Pubkey

from app.clients.solana_rpc import SolanaRpcClient
from app.config import settings
from app.models.merkle import MerkleRoot

logger = logging.getLogger(__name__)

# PDA seed for the canonical Merkle-tree state account.
# Layout assumption: the BagsVault program derives its Merkle-tree state
# PDA from a single seed b"merkle_tree" with no additional discriminators.
# This matches the pattern used by reference Solana mixers (Tornado-style
# anchor programs). Update this seed when the on-chain program is finalized.
_MERKLE_PDA_SEED = b"merkle_tree"

# Layout assumption (after the 8-byte Anchor discriminator):
#     [u8  bump]                # 1 byte
#     [u32 commitment_count]    # 4 bytes (little-endian)
#     [u8;32] root              # 32 bytes — current root
#     [[u8;32]; 10] recent_roots  # 320 bytes — circular buffer of historical roots
# Total fixed header: 8 + 1 + 4 + 32 = 45 bytes before the historical-root buffer.
_DISCRIMINATOR_LEN = 8
_HEADER_LEN = _DISCRIMINATOR_LEN + 1 + 4
_ROOT_LEN = 32

_MISSING_PROGRAM_LOGGED = False


class MerkleIndexer:
    """Maintains the ``db.merkle_roots`` cache from on-chain state."""

    def __init__(self, rpc: SolanaRpcClient, db: AsyncIOMotorDatabase) -> None:
        self._rpc = rpc
        self._db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _derive_merkle_pda(program_id_b58: str) -> str:
        """Derive the canonical Merkle-tree state PDA for the program."""

        program_id = Pubkey.from_string(program_id_b58)
        pda, _bump = Pubkey.find_program_address([_MERKLE_PDA_SEED], program_id)
        return str(pda)

    @staticmethod
    def _decode_account_data(data_field: Any) -> bytes | None:
        """Decode the ``account.data`` field into raw bytes.

        ``getAccountInfo`` returns ``data`` as ``[<encoded_string>, <encoding>]``
        when the encoding is base64. Other encodings are not supported here.
        """

        if not isinstance(data_field, list) or len(data_field) < 2:
            return None
        encoded, encoding = data_field[0], data_field[1]
        if encoding != "base64" or not isinstance(encoded, str):
            return None
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _decode_state(cls, raw: bytes) -> tuple[str, int] | None:
        """Decode ``(root_hex, commitment_count)`` from the account bytes.

        Returns ``None`` if the buffer is too short to contain the documented
        header layout.
        """

        if len(raw) < _HEADER_LEN + _ROOT_LEN:
            return None
        # Layout assumption (see module docstring): skip 8-byte Anchor
        # discriminator + 1-byte bump, read u32 LE commitment_count, then
        # 32 bytes of current root.
        commitment_count = struct.unpack_from("<I", raw, _DISCRIMINATOR_LEN + 1)[0]
        root_bytes = raw[_HEADER_LEN : _HEADER_LEN + _ROOT_LEN]
        return root_bytes.hex(), int(commitment_count)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def sync_now(self) -> MerkleRoot | None:
        """Fetch the current Merkle-tree state and upsert it into Mongo.

        Returns the freshly-recorded :class:`MerkleRoot` on success or
        ``None`` if the program ID is unset, the PDA does not yet exist,
        or the account data cannot be decoded.
        """

        global _MISSING_PROGRAM_LOGGED
        program_id = settings.bagsvault_program_id
        if not program_id:
            if not _MISSING_PROGRAM_LOGGED:
                logger.warning(
                    "MerkleIndexer.sync_now skipped: BAGSVAULT_PROGRAM_ID is not configured."
                )
                _MISSING_PROGRAM_LOGGED = True
            return None

        try:
            pda = self._derive_merkle_pda(program_id)
        except (ValueError, TypeError) as exc:
            logger.warning("MerkleIndexer: invalid program id %s (%s)", program_id, exc)
            return None

        account = await self._rpc.get_account_info(pda, encoding="base64")
        if account is None:
            logger.info("MerkleIndexer: PDA %s does not exist yet", pda)
            return None

        raw = self._decode_account_data(account.get("data"))
        if raw is None:
            logger.warning("MerkleIndexer: could not decode account.data for PDA %s", pda)
            return None

        decoded = self._decode_state(raw)
        if decoded is None:
            logger.warning(
                "MerkleIndexer: account data too short (%d bytes) to contain root header",
                len(raw),
            )
            return None

        root_hex, commitment_count = decoded
        block_height = account.get("rentEpoch")
        if not isinstance(block_height, int):
            block_height = None

        record = MerkleRoot(
            root=root_hex,
            commitment_count=commitment_count,
            block_height=block_height,
            indexed_at=datetime.now(timezone.utc),
            source="indexed",
        )

        try:
            await self._db.merkle_roots.insert_one(record.model_dump())
        except DuplicateKeyError:
            # Already cached — that's fine. Return the existing record so
            # callers can rely on a non-None return when sync succeeded.
            existing = await self._db.merkle_roots.find_one({"root": root_hex}, {"_id": 0})
            if existing is None:
                return record
            return self._from_doc(existing)

        return record

    async def get_recent_roots(self, limit: int = 10) -> list[MerkleRoot]:
        """Return the ``limit`` most recent roots, newest first."""

        cursor = self._db.merkle_roots.find({}, {"_id": 0}).sort("indexed_at", -1).limit(limit)
        roots: list[MerkleRoot] = []
        async for doc in cursor:
            roots.append(self._from_doc(doc))
        return roots

    async def get_current_root(self) -> MerkleRoot | None:
        """Return the most recently indexed root, or ``None`` if cache empty."""

        doc = await self._db.merkle_roots.find_one({}, {"_id": 0}, sort=[("indexed_at", -1)])
        if doc is None:
            return None
        return self._from_doc(doc)

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> MerkleRoot:
        clean = {k: v for k, v in doc.items() if k != "_id"}
        if isinstance(clean.get("indexed_at"), str):
            clean["indexed_at"] = datetime.fromisoformat(clean["indexed_at"])
        return MerkleRoot(**clean)
