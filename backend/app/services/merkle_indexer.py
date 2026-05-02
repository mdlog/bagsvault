"""Merkle-root indexer service.

Best-effort cache of recent BagsVault Merkle-tree roots, populated by
reading the program's on-chain state account. The service is *safe to
call repeatedly* — duplicate roots are upserted as no-ops thanks to the
unique index on ``db.merkle_roots.root``.

The indexer is **not** scheduled here; calling code
(``DepositService``, the Phase 3 :class:`IndexerWorker` background task,
or the optional WebSocket loop in :meth:`subscribe_root_updates`)
decides when to invoke ``sync_now()``.
"""

from __future__ import annotations

import base64
import logging
import struct
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from solders.pubkey import Pubkey

from app.clients.solana_rpc import SolanaRpcClient
from app.config import settings
from app.models.merkle import MerkleRoot

if TYPE_CHECKING:
    from app.clients.anchor_decoder import AnchorDecoder
    from app.clients.solana_ws import SolanaWsClient

logger = logging.getLogger(__name__)

# Default account name used when calling ``AnchorDecoder.decode_account``
# for the merkle-tree state. Matches the on-chain Anchor account struct
# `programs/bagsvault/src/state.rs::MerkleTreeState`. Overridable through
# the constructor in case the program renames the account.
_DEFAULT_MERKLE_ACCOUNT_NAME = "MerkleTreeState"

# PDA seeds for the canonical Merkle-tree state account. The Anchor
# program derives its PDA as `[b"merkle_tree", token_mint]` — the pool
# is keyed per token mint so a single program can host SOL alongside
# any number of SPL pools.
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

    def __init__(
        self,
        rpc: SolanaRpcClient,
        db: AsyncIOMotorDatabase,
        decoder: "AnchorDecoder | None" = None,
        account_name: str = _DEFAULT_MERKLE_ACCOUNT_NAME,
    ) -> None:
        self._rpc = rpc
        self._db = db
        self._decoder = decoder
        self._account_name = account_name

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _derive_merkle_pda(program_id_b58: str) -> str:
        """Derive the canonical Merkle-tree state PDA for the program.

        The on-chain seeds are ``[b"merkle_tree", token_mint]``. For
        the SOL pool the token-mint sentinel is the System Program ID
        (32 bytes of zeros). Other tokens override via
        ``settings.vault_token_mint`` or by calling the indexer with a
        custom seed list.
        """

        program_id = Pubkey.from_string(program_id_b58)
        if settings.vault_token_mint:
            try:
                token_mint = bytes(Pubkey.from_string(settings.vault_token_mint))
            except Exception:  # noqa: BLE001 — fall back to SOL sentinel below
                token_mint = b"\x00" * 32
        else:
            token_mint = b"\x00" * 32
        pda, _bump = Pubkey.find_program_address(
            [_MERKLE_PDA_SEED, token_mint], program_id
        )
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

    @staticmethod
    def _state_from_decoded_dict(decoded: dict[str, Any]) -> tuple[str, int] | None:
        """Extract ``(root_hex, commitment_count)`` from an anchorpy decode.

        We accept any of the common field names a Tornado-style merkle
        program might use (``root`` / ``current_root``,
        ``commitment_count`` / ``next_index`` / ``leaf_count``) so the
        decoder works against multiple IDLs without a code change.
        Returns ``None`` if neither a root nor a counter is present.
        """

        root_value: Any = None
        for key in ("root", "current_root", "currentRoot"):
            if key in decoded:
                root_value = decoded[key]
                break
        if root_value is None:
            return None

        # ``construct`` returns bytes for fixed-size byte arrays. Accept
        # hex strings too (in case anchorpy serialises differently).
        if isinstance(root_value, (bytes, bytearray)):
            root_hex = bytes(root_value).hex()
        elif isinstance(root_value, str):
            root_hex = root_value.lower().removeprefix("0x")
        elif isinstance(root_value, list) and all(isinstance(b, int) for b in root_value):
            root_hex = bytes(root_value).hex()
        else:
            return None

        count_value: Any = 0
        for key in ("commitment_count", "commitmentCount", "next_index", "nextIndex", "leaf_count"):
            if key in decoded:
                count_value = decoded[key]
                break
        try:
            commitment_count = int(count_value)
        except (TypeError, ValueError):
            commitment_count = 0
        if commitment_count < 0:
            commitment_count = 0
        return root_hex, commitment_count

    async def _decode_with_idl(self, account_data_b64: str) -> tuple[str, int] | None:
        """Try the IDL-based decoder; return ``None`` if unavailable/failed."""

        if self._decoder is None or not self._decoder.decode_available():
            return None
        decoded = await self._decoder.decode_account(account_data_b64, self._account_name)
        if not decoded:
            return None
        return self._state_from_decoded_dict(decoded)

    @staticmethod
    def _extract_b64(data_field: Any) -> str | None:
        """Return the base64 string from a ``[<b64>, "base64"]`` data field."""

        if not isinstance(data_field, list) or len(data_field) < 2:
            return None
        encoded, encoding = data_field[0], data_field[1]
        if encoding != "base64" or not isinstance(encoded, str):
            return None
        return encoded

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

        return await self._record_from_account(account)

    async def _record_from_account(self, account: dict[str, Any]) -> MerkleRoot | None:
        """Decode a ``getAccountInfo``-style payload and upsert it.

        Tries the optional anchorpy decoder first (when an IDL is loaded)
        and falls back to the manual layout decode used in Phase 2A.
        Returns the freshly-cached :class:`MerkleRoot` or ``None`` if no
        decoder could parse the buffer.
        """

        b64 = self._extract_b64(account.get("data"))
        if b64 is None:
            logger.warning("MerkleIndexer: could not extract base64 from account.data")
            return None

        # Prefer the IDL-based decoder when available; fall back to the
        # hand-rolled layout decode otherwise.
        decoded = await self._decode_with_idl(b64)
        if decoded is None:
            try:
                raw = base64.b64decode(b64)
            except (ValueError, TypeError) as exc:
                logger.warning("MerkleIndexer: bad base64 account data (%s)", exc)
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

    async def subscribe_root_updates(self, ws: "SolanaWsClient") -> AsyncIterator[MerkleRoot]:
        """Stream new merkle roots over a WebSocket ``accountSubscribe``.

        The async iterator yields a :class:`MerkleRoot` every time the
        on-chain merkle PDA changes. Notifications that arrive without
        a parsable account payload are silently skipped so a malformed
        message can't break the loop.

        The caller is responsible for owning the ``SolanaWsClient`` and
        the surrounding asyncio task.
        """

        program_id = settings.bagsvault_program_id
        if not program_id:
            logger.warning(
                "MerkleIndexer.subscribe_root_updates skipped: BAGSVAULT_PROGRAM_ID is not set."
            )
            return

        try:
            pda = self._derive_merkle_pda(program_id)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "MerkleIndexer.subscribe_root_updates: invalid program id %s (%s)",
                program_id,
                exc,
            )
            return

        async for notification in ws.subscribe_account(pda, encoding="base64"):
            account = self._extract_account_from_notification(notification)
            if account is None:
                continue
            record = await self._record_from_account(account)
            if record is not None:
                yield record

    @staticmethod
    def _extract_account_from_notification(notification: dict[str, Any]) -> dict[str, Any] | None:
        """Pull the ``account`` dict out of a ``solders``-style notification.

        Solana ``accountNotification`` payloads serialise (via
        ``to_json``) to either::

            {"result": {"context": {...}, "value": {"account": {...}, ...}}}
            {"result": {"context": {...}, "value": {"data": [...], ...}}}

        depending on the SDK version. We accept both shapes and any
        nested ``params.result.value`` form for the raw JSON-RPC
        envelope.
        """

        candidates = [notification]
        # Walk a couple of likely envelope keys to find a dict that
        # looks like ``getAccountInfo``'s ``value`` field (i.e. has a
        # ``data`` list).
        result = notification.get("result")
        if isinstance(result, dict):
            candidates.append(result)
            value = result.get("value")
            if isinstance(value, dict):
                candidates.append(value)
                inner = value.get("account")
                if isinstance(inner, dict):
                    candidates.append(inner)
        params = notification.get("params")
        if isinstance(params, dict):
            inner_result = params.get("result")
            if isinstance(inner_result, dict):
                candidates.append(inner_result)
                value = inner_result.get("value")
                if isinstance(value, dict):
                    candidates.append(value)

        for candidate in candidates:
            data = candidate.get("data") if isinstance(candidate, dict) else None
            if isinstance(data, list) and len(data) >= 2:
                return candidate
        return None

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
