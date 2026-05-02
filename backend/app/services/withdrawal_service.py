"""Withdrawal orchestration service.

Encapsulates the full server-side withdrawal pipeline:

1. Reject if the nullifier hash has already been claimed (double-spend
   guard backed by the unique index on ``db.withdrawals``).
2. Bail with HTTP 503 when ``BAGSVAULT_PROGRAM_ID`` is empty so the
   operator gets a clear "not configured" signal instead of a vague
   on-chain error.
3. Build a Solana ``withdraw`` instruction targeting the BagsVault
   Anchor program. The exact ix layout is documented inline at the call
   site — when the on-chain ABI lands the only thing that has to change
   is the constants in :func:`_build_withdraw_ix`.
4. Sign with the relayer keypair, broadcast via the JSON-RPC client,
   and persist a Withdrawal row keyed by ``nullifier_hash`` so the
   double-spend guard catches replays.

Anything that fails before broadcast surfaces as a domain error so the
FastAPI handler returns a structured JSON response. Anything that fails
*after* broadcast (e.g. Mongo write fails after we have a tx signature)
is logged and the signature is still returned — the chain is the source
of truth.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from app.clients.solana_signer import SolanaSignerClient
from app.config import settings
from app.exceptions import (
    BagsVaultError,
    ConflictError,
    ServiceUnavailableError,
    UpstreamError,
    ValidationError,
)
from app.models.relayer import Relayer
from app.models.withdrawal import Withdrawal, WithdrawalRelayRequest
from app.services.relayer_service import RelayerService

logger = logging.getLogger(__name__)


# Layout assumption for the BagsVault `withdraw` instruction:
#   * Anchor discriminator at instruction byte 0..8 (placeholder until
#     IDL lands — we use ix_index=2 to mean "third Anchor handler").
#   * Account order (matches the docstring contract in the task spec):
#       0. program (BagsVault)              — read-only
#       1. verifier (Sunspot Groth16)       — read-only
#       2. recipient (target wallet)        — writable
#       3. relayer (this signer)            — writable + signer
#       4. nullifier PDA                    — writable
#       5. root account (Merkle root cache) — read-only
# The constants below mirror that contract; replace with IDL-derived
# values once the program is deployed.
WITHDRAW_IX_INDEX = 2
WITHDRAW_DISCRIMINATOR = b"withdraw"  # placeholder — real ix uses 8-byte Anchor sighash
SOL_TOKEN_SENTINEL = "SOL"


class SolanaRpc(Protocol):
    """Subset of :class:`app.clients.solana_rpc.SolanaRpcClient` we depend on.

    Declared here as a Protocol so this module compiles cleanly even if
    Agent A's RPC client lands later. Tests inject any object that
    implements these three async methods. ``get_recent_blockhash``
    returns the raw ``getLatestBlockhash`` payload
    (``{"blockhash": str, "lastValidBlockHeight": int}``) — we accept
    either that dict or a bare blockhash string for forward-compat.
    """

    async def get_recent_blockhash(self) -> Any: ...

    async def send_transaction(self, signed_tx_b64: str, skip_preflight: bool = False) -> str: ...

    async def get_transaction(self, sig: str) -> dict[str, Any] | None: ...


def _coerce_blockhash(raw: Any) -> str:
    """Accept either a raw blockhash string or the modern dict envelope."""

    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        value = raw.get("blockhash")
        if isinstance(value, str):
            return value
    raise UpstreamError(
        "Solana RPC returned an unexpected blockhash payload.",
        details={"type": type(raw).__name__},
    )


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


def _short_hash(sig: str) -> str:
    """Render a tx signature like the frontend does: ``5a2f…9c1b``."""

    if len(sig) <= 8:
        return sig
    return f"{sig[:4]}…{sig[-4:]}"


def _relative_time(dt: datetime) -> str:
    """Compact "Xm ago" / "Xh ago" / "Xd ago" string."""

    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _hex_to_bytes(value: str, *, label: str) -> bytes:
    """Decode a hex string (with or without ``0x``) or raise ``ValidationError``."""

    cleaned = value[2:] if value.lower().startswith("0x") else value
    try:
        return binascii.unhexlify(cleaned)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError(
            f"Invalid hex value for {label}.",
            details={"field": label, "error": str(exc)},
        ) from exc


def _decode_recipient(recipient: str) -> Pubkey:
    try:
        return Pubkey.from_string(recipient)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            "recipient is not a valid base58 Solana pubkey.",
            details={"recipient": recipient, "error": str(exc)},
        ) from exc


def _build_withdraw_ix(
    *,
    program_id: Pubkey,
    verifier_id: Pubkey,
    recipient: Pubkey,
    relayer: Pubkey,
    proof_bytes: bytes,
    root_bytes: bytes,
    nullifier_bytes: bytes,
    amount: int,
) -> Instruction:
    """Build the Anchor ``withdraw`` instruction.

    See the module-level layout assumption block. The instruction data
    layout is:

    ``[discriminator(8) | ix_index(1) | amount(8 LE) | root(32) |
    nullifier(32) | proof_len(4 LE) | proof_bytes]``

    This matches what the BagsVault Anchor program is expected to
    deserialize. Once the IDL is published, replace the discriminator
    with the real Anchor sighash and pull the rest from anchorpy.
    """

    # Pad / truncate root + nullifier to 32 bytes — most ZK schemes
    # serialize them as exactly that, but operator-supplied hex may be
    # short (leading zeros stripped) so we left-pad defensively.
    root32 = root_bytes.rjust(32, b"\x00")[-32:]
    nullifier32 = nullifier_bytes.rjust(32, b"\x00")[-32:]

    data = bytearray()
    data += WITHDRAW_DISCRIMINATOR.ljust(8, b"\x00")[:8]
    data += WITHDRAW_IX_INDEX.to_bytes(1, "little")
    data += int(amount).to_bytes(8, "little")
    data += root32
    data += nullifier32
    data += len(proof_bytes).to_bytes(4, "little")
    data += proof_bytes

    accounts = [
        AccountMeta(pubkey=program_id, is_signer=False, is_writable=False),
        AccountMeta(pubkey=verifier_id, is_signer=False, is_writable=False),
        AccountMeta(pubkey=recipient, is_signer=False, is_writable=True),
        AccountMeta(pubkey=relayer, is_signer=True, is_writable=True),
        # Nullifier + root PDAs would normally be derived via
        # find_program_address(...). Until we have the real seeds we
        # advertise them as the program itself so the ix shape is
        # stable and the program can re-derive at runtime.
        AccountMeta(pubkey=program_id, is_signer=False, is_writable=True),
        AccountMeta(pubkey=program_id, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=bytes(data))


class WithdrawalService:
    """Orchestrates the relay → sign → broadcast → persist pipeline."""

    def __init__(
        self,
        rpc: SolanaRpc,
        signer: SolanaSignerClient,
        relayers: RelayerService,
        db: AsyncIOMotorDatabase,
    ) -> None:
        self._rpc = rpc
        self._signer = signer
        self._relayers = relayers
        self._db = db

    # ------------------------------------------------------------------
    # Relay pipeline
    # ------------------------------------------------------------------
    async def relay(self, payload: WithdrawalRelayRequest) -> dict[str, Any]:
        """Run the eight-step relay pipeline for a single withdrawal."""

        public_inputs = payload.public_inputs

        # Step 2: nullifier double-spend guard.
        existing = await self._db.withdrawals.find_one(
            {"nullifier_hash": public_inputs.nullifier_hash}
        )
        if existing:
            raise ConflictError(
                "Nullifier already spent.",
                details={"nullifier_hash": public_inputs.nullifier_hash},
            )

        # Step 3: program configuration guard.
        if not settings.bagsvault_program_id:
            raise ServiceUnavailableError(
                "BAGSVAULT_PROGRAM_ID is not configured.",
                details={"missing_env": "BAGSVAULT_PROGRAM_ID"},
            )
        if not settings.bagsvault_verifier_id:
            raise ServiceUnavailableError(
                "BAGSVAULT_VERIFIER_ID is not configured.",
                details={"missing_env": "BAGSVAULT_VERIFIER_ID"},
            )

        try:
            program_id = Pubkey.from_string(settings.bagsvault_program_id)
            verifier_id = Pubkey.from_string(settings.bagsvault_verifier_id)
        except Exception as exc:  # noqa: BLE001
            raise ServiceUnavailableError(
                "BagsVault program/verifier id is not a valid base58 pubkey.",
                details={
                    "program_id": settings.bagsvault_program_id,
                    "verifier_id": settings.bagsvault_verifier_id,
                    "error": str(exc),
                },
            ) from exc

        # Pick a relayer (this node is registered via seed_relayers.py).
        relayer: Relayer = await self._relayers.pick_best(token=public_inputs.token)

        # Step 4: build the on-chain withdraw instruction.
        proof_bytes = _hex_to_bytes(payload.proof, label="proof")
        root_bytes = _hex_to_bytes(public_inputs.root, label="public_inputs.root")
        nullifier_bytes = _hex_to_bytes(
            public_inputs.nullifier_hash, label="public_inputs.nullifier_hash"
        )
        recipient_pubkey = _decode_recipient(public_inputs.recipient)

        relayer_pubkey = self._signer.pubkey_obj()
        ix = _build_withdraw_ix(
            program_id=program_id,
            verifier_id=verifier_id,
            recipient=recipient_pubkey,
            relayer=relayer_pubkey,
            proof_bytes=proof_bytes,
            root_bytes=root_bytes,
            nullifier_bytes=nullifier_bytes,
            amount=public_inputs.amount,
        )

        # Step 5/6: blockhash → sign → broadcast.
        try:
            blockhash_payload = await self._rpc.get_recent_blockhash()
        except BagsVaultError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(
                "Failed to fetch recent blockhash from Solana RPC.",
                details={"error": str(exc)},
            ) from exc

        recent_blockhash = _coerce_blockhash(blockhash_payload)

        try:
            signed = self._signer.build_and_sign(
                instructions=[ix],
                recent_blockhash=recent_blockhash,
                payer=relayer_pubkey,
            )
        except BagsVaultError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ServiceUnavailableError(
                "Failed to build and sign withdrawal transaction.",
                details={"error": str(exc)},
            ) from exc

        signed_b64 = base64.b64encode(signed).decode("ascii")
        try:
            signature = await self._rpc.send_transaction(signed_b64, skip_preflight=False)
        except BagsVaultError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(
                "Solana RPC rejected the withdrawal transaction.",
                details={"error": str(exc)},
            ) from exc

        # Step 7: persist (best-effort — the chain is the truth).
        record = Withdrawal(
            nullifier_hash=public_inputs.nullifier_hash,
            recipient=public_inputs.recipient,
            amount=public_inputs.amount,
            token=public_inputs.token,
            relayer_id=relayer.relayer_id,
            tx_signature=signature,
        )
        try:
            await self._db.withdrawals.insert_one(record.model_dump())
        except Exception as exc:  # noqa: BLE001 — never block a successful tx
            logger.warning(
                "withdrawal persisted-only-on-chain nullifier=%s sig=%s err=%s",
                public_inputs.nullifier_hash,
                signature,
                exc,
            )

        # Touch the relayer's last_seen so the leaderboard reflects activity.
        try:
            await self._db.relayers.update_one(
                {"relayer_id": relayer.relayer_id},
                {"$set": {"last_seen": record.created_at}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("relayer last_seen update skipped: %s", exc)

        logger.info(
            "withdrawal.relay sig=%s relayer=%s recipient=%s amount=%d token=%s",
            signature,
            relayer.relayer_id,
            public_inputs.recipient,
            public_inputs.amount,
            public_inputs.token,
        )
        return {"signature": signature, "status": "submitted"}

    # ------------------------------------------------------------------
    # Anonymized listing
    # ------------------------------------------------------------------
    async def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent withdrawals with the recipient stripped.

        The frontend's ``Recent withdrawals`` panel only needs short
        hash, amount, token, relayer name, and a relative timestamp.
        Recipient addresses are intentionally omitted to honor the
        protocol's anonymity contract.
        """

        cursor = self._db.withdrawals.find().sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)

        # Resolve relayer names in a single Mongo round-trip.
        relayer_ids = sorted({doc.get("relayer_id") for doc in docs if doc.get("relayer_id")})
        names: dict[str, str] = {}
        if relayer_ids:
            relayer_cursor = self._db.relayers.find(
                {"relayer_id": {"$in": list(relayer_ids)}},
                {"_id": 0, "relayer_id": 1, "name": 1},
            )
            async for r_doc in relayer_cursor:
                rid = r_doc.get("relayer_id")
                name = r_doc.get("name")
                if isinstance(rid, str) and isinstance(name, str):
                    names[rid] = name

        out: list[dict[str, Any]] = []
        for doc in docs:
            clean = _strip_id(doc)
            created_at = clean.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = None
            sig = clean.get("tx_signature", "")
            relayer_id = clean.get("relayer_id", "")
            out.append(
                {
                    "hash": _short_hash(str(sig)) if sig else "",
                    "tx_signature": sig,
                    "amount": clean.get("amount", 0),
                    "token": clean.get("token", ""),
                    "relayer_name": names.get(str(relayer_id), str(relayer_id)),
                    "relative_time": (
                        _relative_time(created_at) if isinstance(created_at, datetime) else ""
                    ),
                }
            )
        return out
