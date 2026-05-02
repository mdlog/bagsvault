"""Deposit instruction builder.

The frontend can't talk to the on-chain ``deposit(commitment)`` ix
directly without an Anchor IDL parser in the browser. Instead it asks
this service to build an *unsigned* v0 transaction and hands it to the
user's wallet for signing + broadcast. This mirrors the pattern used
by ``scripts/launch_vault_token.py`` (which prints an unsigned tx for
manual signing) but exposed over HTTP for the deposit flow.

Layout assumption — must match
``programs/bagsvault/src/instructions/deposit.rs``:

* Anchor sighash = ``sha256("global:deposit")[..8]``.
* Account order (``Deposit<'info>``):
    0. depositor (signer, writable) — funds the deposit.
    1. vault PDA (writable) — derived from ``[b"vault", token_mint]``.
    2. tree_state PDA (writable) — ``[b"merkle_tree", token_mint]``.
    3. system_program (read-only).
* Borsh args: ``commitment: [u8; 32]``.

If the service later needs to support fee-payer relayers (gasless
deposits), an extra signer account would be appended; the current shape
matches the simplest "depositor pays gas" path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from typing import Any

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from app.config import settings
from app.exceptions import (
    BagsVaultError,
    ServiceUnavailableError,
    UpstreamError,
    ValidationError,
)

logger = logging.getLogger(__name__)


# Anchor instruction discriminator = first 8 bytes of
# ``sha256("global:deposit")``. Computed lazily from the canonical name
# string so the test pin matches the on-chain handler exactly.
DEPOSIT_SIGHASH = hashlib.sha256(b"global:deposit").digest()[:8]

# Sentinel matching the rest of the codebase ("SOL" → system program ID).
SOL_TOKEN_SENTINEL = "SOL"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# PDA seeds — must mirror programs/bagsvault/src/state.rs + deposit.rs.
MERKLE_TREE_SEED = b"merkle_tree"
VAULT_SEED = b"vault"


def _hex_to_bytes32(value: str, *, label: str) -> bytes:
    """Decode a hex string (with or without ``0x``) and pad/truncate to 32 bytes.

    Raises :class:`ValidationError` for non-hex input. Left-pads with
    zeros if the operator-supplied value is short (leading zeros stripped
    is a common ZK-tooling quirk).
    """

    cleaned = value[2:] if value.lower().startswith("0x") else value
    try:
        raw = binascii.unhexlify(cleaned)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError(
            f"Invalid hex value for {label}.",
            details={"field": label, "error": str(exc)},
        ) from exc
    return raw.rjust(32, b"\x00")[-32:]


def _resolve_token_mint(token_mint: str) -> Pubkey:
    """Translate ``"SOL"`` to the system program ID and parse base58.

    Mirrors ``withdrawal_service._resolve_token_mint`` so the two flows
    converge on the same mint sentinel rules. Raises
    :class:`ValidationError` for malformed base58 mints so the FastAPI
    handler returns HTTP 400.
    """

    if token_mint == SOL_TOKEN_SENTINEL or not token_mint:
        return Pubkey.from_string(SYSTEM_PROGRAM_ID)
    try:
        return Pubkey.from_string(token_mint)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            "token must be 'SOL' or a base58 SPL mint pubkey.",
            details={"token": token_mint, "error": str(exc)},
        ) from exc


def _decode_pubkey(raw: str, *, label: str) -> Pubkey:
    try:
        return Pubkey.from_string(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            f"{label} is not a valid base58 Solana pubkey.",
            details={"field": label, "value": raw, "error": str(exc)},
        ) from exc


def _build_deposit_ix(
    *,
    program_id: Pubkey,
    depositor: Pubkey,
    vault: Pubkey,
    tree_state: Pubkey,
    commitment: bytes,
) -> Instruction:
    """Build the Anchor ``deposit`` instruction.

    See the module-level layout assumption block. Instruction data
    layout: ``[sighash(8) | commitment(32)]``.
    """

    if len(commitment) != 32:
        raise ValidationError(
            "commitment must be exactly 32 bytes.",
            details={"actual_len": len(commitment)},
        )

    data = bytearray()
    data += DEPOSIT_SIGHASH
    data += commitment

    accounts = [
        AccountMeta(pubkey=depositor, is_signer=True, is_writable=True),
        AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
        AccountMeta(pubkey=tree_state, is_signer=False, is_writable=True),
        AccountMeta(pubkey=Pubkey.from_string(SYSTEM_PROGRAM_ID), is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=bytes(data))


class _RpcLike:
    """Protocol-style hint — see ``withdrawal_service.SolanaRpc``."""

    async def get_recent_blockhash(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def _coerce_blockhash(raw: Any) -> str:
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


class DepositBuilder:
    """Builds unsigned deposit transactions for the frontend to sign."""

    def __init__(self, rpc: Any) -> None:
        self._rpc = rpc

    async def build_unsigned_tx(
        self,
        *,
        commitment_hex: str,
        amount_lamports: int,
        depositor: Pubkey | str,
        token_mint: str = SOL_TOKEN_SENTINEL,
    ) -> dict[str, Any]:
        """Compile the unsigned v0 deposit transaction.

        Returns a dict with the base64-encoded unsigned tx, the blockhash
        used (so the frontend knows when it expires), and the derived
        PDAs. The caller signs + broadcasts; this service never touches
        the user's secret key.

        ``amount_lamports`` is informational only — the on-chain program
        reads the denomination from ``tree_state`` and ignores any
        client-supplied amount. We surface it back so the frontend can
        cross-check against the pool's fixed denomination.
        """

        if not settings.bagsvault_program_id:
            raise ServiceUnavailableError(
                "BAGSVAULT_PROGRAM_ID is not configured.",
                details={"missing_env": "BAGSVAULT_PROGRAM_ID"},
            )

        try:
            program_id = Pubkey.from_string(settings.bagsvault_program_id)
        except Exception as exc:  # noqa: BLE001
            raise ServiceUnavailableError(
                "BAGSVAULT_PROGRAM_ID is not a valid base58 pubkey.",
                details={"program_id": settings.bagsvault_program_id, "error": str(exc)},
            ) from exc

        commitment = _hex_to_bytes32(commitment_hex, label="commitment")
        token_mint_pubkey = _resolve_token_mint(token_mint)

        if isinstance(depositor, Pubkey):
            depositor_pubkey = depositor
        else:
            depositor_pubkey = _decode_pubkey(depositor, label="depositor_pubkey")

        # Derive PDAs — match the on-chain seeds exactly.
        vault, _vault_bump = Pubkey.find_program_address(
            [VAULT_SEED, bytes(token_mint_pubkey)], program_id
        )
        tree_state, _tree_bump = Pubkey.find_program_address(
            [MERKLE_TREE_SEED, bytes(token_mint_pubkey)], program_id
        )

        ix = _build_deposit_ix(
            program_id=program_id,
            depositor=depositor_pubkey,
            vault=vault,
            tree_state=tree_state,
            commitment=commitment,
        )

        # Pull a fresh blockhash. We accept either the modern dict
        # envelope (Agent A's RPC client) or a bare string.
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
            blockhash_obj = Hash.from_string(recent_blockhash)
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(
                "Solana RPC returned a malformed blockhash.",
                details={"blockhash": recent_blockhash, "error": str(exc)},
            ) from exc

        message = MessageV0.try_compile(
            payer=depositor_pubkey,
            instructions=[ix],
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash_obj,
        )

        # Build an *unsigned* VersionedTransaction. ``populate`` accepts
        # a list of pre-existing signatures; passing the message's
        # required-signer count of empty (default) signatures yields a
        # tx the frontend can fill in via wallet.signTransaction(...).
        num_signers = message.header.num_required_signatures
        empty_sigs = [Signature.default() for _ in range(num_signers)]
        unsigned = VersionedTransaction.populate(message, empty_sigs)
        tx_bytes = bytes(unsigned)
        tx_b64 = base64.b64encode(tx_bytes).decode("ascii")

        logger.info(
            "deposits.build_unsigned_tx commitment=%s depositor=%s amount=%d token=%s",
            commitment.hex()[:12],
            depositor_pubkey,
            amount_lamports,
            token_mint,
        )

        return {
            "tx_base64": tx_b64,
            "blockhash": recent_blockhash,
            "tree_state_pda": str(tree_state),
            "vault_pda": str(vault),
            "program_id": str(program_id),
            "depositor": str(depositor_pubkey),
            "amount": int(amount_lamports),
            "token": token_mint,
            "commitment": commitment.hex(),
        }
