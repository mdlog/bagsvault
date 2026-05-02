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
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID

from app.clients.solana_signer import SolanaSignerClient
from app.clients.tx_executor import TxExecutor
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


# ----------------------------------------------------------------------
# Anchor instruction layout (BagsVault.withdraw).
# ----------------------------------------------------------------------
# Account order MUST match
# `programs/bagsvault/src/instructions/withdraw.rs::Withdraw`:
#   0. relayer            (signer, writable)
#   1. vault              (writable, PDA [b"vault", token_mint])
#   2. tree_state         (writable, PDA [b"merkle_tree", token_mint])
#   3. nullifier_pda      (writable, PDA [b"nullifier", nullifier_hash])
#   4. recipient_account  (writable)
#   5. system_program     (read-only)
#
# Instruction data layout uses Anchor's standard sighash + Borsh body:
#   discriminator(8) | proof_len(4 LE) | proof_bytes
#                    | root(32) | nullifier_hash(32)
#                    | recipient(32) | amount(8 LE)
SOL_TOKEN_SENTINEL = "SOL"
# Anchor's per-instruction sighash. We compute it on import so we never
# get out-of-sync with the program's `pub fn withdraw(...)` name.
WITHDRAW_SIGHASH = hashlib.sha256(b"global:withdraw").digest()[:8]
MERKLE_TREE_SEED = b"merkle_tree"
VAULT_SEED = b"vault"
NULLIFIER_SEED = b"nullifier"


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


def _rpc_supports_executor(rpc: Any) -> bool:
    """Return True iff ``rpc`` exposes the methods :class:`TxExecutor` needs."""

    return hasattr(rpc, "simulate_transaction") and hasattr(rpc, "get_signature_statuses")


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


def _resolve_token_mint(token: str) -> Pubkey:
    """Resolve the pool's token-mint pubkey from the request's token tag.

    The on-chain program treats the System Program ID as the sentinel
    mint for native-SOL pools. Any other value must be a base58 mint.
    """

    if token == SOL_TOKEN_SENTINEL or not token:
        return SYSTEM_PROGRAM_ID
    if settings.vault_token_mint and token in {"VAULT", settings.vault_token_mint}:
        return Pubkey.from_string(settings.vault_token_mint)
    try:
        return Pubkey.from_string(token)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            "Unknown token tag for withdrawal — supply 'SOL', 'VAULT', or a base58 mint.",
            details={"token": token, "error": str(exc)},
        ) from exc


def _derive_pdas(
    program_id: Pubkey, token_mint: Pubkey, nullifier_bytes32: bytes
) -> tuple[Pubkey, Pubkey, Pubkey]:
    """Return ``(vault, tree_state, nullifier_pda)`` PDAs."""

    vault, _ = Pubkey.find_program_address([VAULT_SEED, bytes(token_mint)], program_id)
    tree_state, _ = Pubkey.find_program_address(
        [MERKLE_TREE_SEED, bytes(token_mint)], program_id
    )
    nullifier_pda, _ = Pubkey.find_program_address(
        [NULLIFIER_SEED, nullifier_bytes32], program_id
    )
    return vault, tree_state, nullifier_pda


def _build_withdraw_ix(
    *,
    program_id: Pubkey,
    token_mint: Pubkey,
    recipient: Pubkey,
    relayer: Pubkey,
    proof_bytes: bytes,
    root_bytes: bytes,
    nullifier_bytes: bytes,
    amount: int,
) -> Instruction:
    """Build the Anchor ``withdraw`` instruction.

    Matches the on-chain Anchor program at
    ``programs/bagsvault/src/instructions/withdraw.rs``. PDAs are
    derived deterministically so a client doesn't need to round-trip an
    extra RPC call to learn them.
    """

    root32 = root_bytes.rjust(32, b"\x00")[-32:]
    nullifier32 = nullifier_bytes.rjust(32, b"\x00")[-32:]

    vault_pda, tree_state_pda, nullifier_pda = _derive_pdas(
        program_id, token_mint, nullifier32
    )

    data = bytearray()
    data += WITHDRAW_SIGHASH
    # Borsh: Vec<u8> is len(u32 LE) || bytes.
    data += len(proof_bytes).to_bytes(4, "little")
    data += proof_bytes
    data += root32
    data += nullifier32
    data += bytes(recipient)
    data += int(amount).to_bytes(8, "little")

    accounts = [
        AccountMeta(pubkey=relayer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=tree_state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=nullifier_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=recipient, is_signer=False, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
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
        executor: TxExecutor | None = None,
    ) -> None:
        self._rpc = rpc
        self._signer = signer
        self._relayers = relayers
        self._db = db
        # The executor encapsulates simulate -> broadcast -> confirm with
        # retry. We build it lazily here only when the injected ``rpc``
        # actually exposes the methods it requires
        # (``simulate_transaction`` + ``get_signature_statuses``). Older
        # tests that inject a minimal RPC stub fall through to the legacy
        # inline broadcast path below.
        if executor is not None:
            self._executor: TxExecutor | None = executor
        elif _rpc_supports_executor(rpc):
            self._executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=settings)
        else:
            self._executor = None

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

        try:
            program_id = Pubkey.from_string(settings.bagsvault_program_id)
        except Exception as exc:  # noqa: BLE001
            raise ServiceUnavailableError(
                "BagsVault program id is not a valid base58 pubkey.",
                details={
                    "program_id": settings.bagsvault_program_id,
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
        token_mint = _resolve_token_mint(public_inputs.token)

        relayer_pubkey = self._signer.pubkey_obj()
        ix = _build_withdraw_ix(
            program_id=program_id,
            token_mint=token_mint,
            recipient=recipient_pubkey,
            relayer=relayer_pubkey,
            proof_bytes=proof_bytes,
            root_bytes=root_bytes,
            nullifier_bytes=nullifier_bytes,
            amount=public_inputs.amount,
        )

        # Step 5/6/7: simulate → broadcast → confirm with retry.
        # Production code paths inject an RPC client that supports the
        # full surface (``simulate_transaction`` + ``get_signature_statuses``)
        # so :class:`TxExecutor` handles the lifecycle. Legacy/minimal
        # stubs fall back to the original inline broadcast path so older
        # tests keep working without the executor's polling machinery.
        if self._executor is not None:
            try:
                tx_result = await self._executor.send(
                    instructions=[ix],
                    payer=relayer_pubkey,
                )
            except BagsVaultError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise UpstreamError(
                    "Solana RPC rejected the withdrawal transaction.",
                    details={"error": str(exc)},
                ) from exc
            signature = tx_result.signature
        else:
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
