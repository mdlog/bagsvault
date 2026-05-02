"""Swap-then-deposit orchestrator.

Architecture doc Section 2.B promises that a creator can hand the
backend "this token, this amount" and receive back two unsigned
transactions to sign and submit in order:

    1. ``swap_tx``    — routes ``input_mint`` to ``output_mint`` via the
       Bags trade API. The caller's wallet signs and broadcasts; once it
       lands, the wallet now holds ``output_mint`` in the right amount.
    2. ``deposit_tx`` — Anchor ``deposit(commitment)`` against the
       BagsVault privacy pool whose ``token_mint == output_mint``. The
       caller's wallet signs again and broadcasts. The pool's vault PDA
       receives the funds, the commitment lands as a Merkle leaf.

The backend NEVER signs either transaction. Holding a user's keys would
defeat the entire privacy contract — the swap output is a public on-chain
transfer that an indexer could trivially correlate with the deposit if
both signatures came from the same hot wallet. Returning two unsigned
artefacts pushes the signing decision to the user's wallet, which is the
right trust boundary.

The service is intentionally thin: it owns shape-normalisation of the
swap response (Bags returns base64 unsigned txs under several keys
depending on the route type) and wraps the deposit ix builder so callers
don't have to know about Anchor sighashes. Everything else lives in
:class:`BagsAPIClient` and the (yet-to-land) full deposit-builder.
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
from solders.null_signer import NullSigner
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction

from app.clients.bags_api import BagsAPIClient
from app.config import settings
from app.exceptions import ServiceUnavailableError, ValidationError

logger = logging.getLogger(__name__)


# Anchor sighash for `pub fn deposit(...)`. Computed on import so we never
# drift from the on-chain program's `pub fn deposit` name.
DEPOSIT_SIGHASH = hashlib.sha256(b"global:deposit").digest()[:8]
MERKLE_TREE_SEED = b"merkle_tree"
VAULT_SEED = b"vault"

# A throwaway blockhash for placeholder unsigned tx serialisation. The
# wallet replaces it with a fresh blockhash before signing — we just need
# *something* the serialiser will accept. Using all-zero keeps the field
# obviously a placeholder so a caller who forgets to refresh sees the
# resulting tx fail simulation immediately.
_PLACEHOLDER_BLOCKHASH = Hash.from_string("11111111111111111111111111111111")


def _hex_to_bytes32(value: str, *, label: str) -> bytes:
    cleaned = value[2:] if value.lower().startswith("0x") else value
    try:
        raw = binascii.unhexlify(cleaned)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError(
            f"Invalid hex value for {label}.",
            details={"field": label, "error": str(exc)},
        ) from exc
    if len(raw) > 32:
        raise ValidationError(
            f"{label} is longer than 32 bytes.",
            details={"field": label, "len": len(raw)},
        )
    return raw.rjust(32, b"\x00")[-32:]


def _decode_pubkey(value: str, *, label: str) -> Pubkey:
    try:
        return Pubkey.from_string(value)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            f"{label} is not a valid base58 Solana pubkey.",
            details={"field": label, "value": value, "error": str(exc)},
        ) from exc


def _extract_swap_tx_b64(raw: dict[str, Any]) -> str:
    """Pull the base64-encoded unsigned swap tx out of a Bags swap response.

    Bags' ``/trade/swap`` payload shape is not formally documented; we
    look at the keys most likely to carry the unsigned bytes in priority
    order. The first non-empty match wins. Raises
    :class:`ServiceUnavailableError` when nothing matches so the operator
    gets a clear "upstream shape changed" signal.
    """

    # Most-likely-singleton key.
    candidate = raw.get("transaction") or raw.get("tx") or raw.get("swapTransaction")
    if isinstance(candidate, str) and candidate:
        return candidate
    # Or an envelope.
    for key in ("transactions", "txs"):
        items = raw.get(key)
        if isinstance(items, list) and items and isinstance(items[0], str):
            return items[0]
    # Nested under data.
    data = raw.get("data")
    if isinstance(data, dict):
        nested = data.get("transaction") or data.get("swapTransaction")
        if isinstance(nested, str) and nested:
            return nested
    raise ServiceUnavailableError(
        "Bags swap response did not include an unsigned transaction.",
        details={"upstream": "bags", "keys": sorted(raw.keys())},
    )


def _derive_deposit_pdas(program_id: Pubkey, token_mint: Pubkey) -> tuple[Pubkey, Pubkey]:
    """Return ``(vault, tree_state)`` PDAs for the pool keyed on ``token_mint``."""

    vault, _ = Pubkey.find_program_address([VAULT_SEED, bytes(token_mint)], program_id)
    tree_state, _ = Pubkey.find_program_address(
        [MERKLE_TREE_SEED, bytes(token_mint)], program_id
    )
    return vault, tree_state


def build_deposit_ix(
    *,
    program_id: Pubkey,
    token_mint: Pubkey,
    depositor: Pubkey,
    commitment_bytes32: bytes,
) -> Instruction:
    """Build the Anchor ``deposit(commitment)`` instruction.

    Mirrors ``programs/bagsvault/src/instructions/deposit.rs::Deposit``
    account ordering exactly:
        0. depositor       (signer, writable)
        1. vault           (writable, PDA [b"vault", token_mint])
        2. tree_state      (writable, PDA [b"merkle_tree", token_mint])
        3. system_program  (read-only)

    Instruction data layout: ``sighash(8) | commitment(32)``. The
    commitment is a fixed-length array, so Borsh emits the bytes inline
    without a length prefix.
    """

    if len(commitment_bytes32) != 32:
        raise ValidationError(
            "commitment must be exactly 32 bytes.",
            details={"len": len(commitment_bytes32)},
        )

    vault_pda, tree_state_pda = _derive_deposit_pdas(program_id, token_mint)

    data = bytearray()
    data += DEPOSIT_SIGHASH
    data += commitment_bytes32

    accounts = [
        AccountMeta(pubkey=depositor, is_signer=True, is_writable=True),
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=tree_state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=bytes(data))


def _serialize_unsigned_tx(ix: Instruction, payer: Pubkey) -> str:
    """Serialise a single-ix VersionedTransaction (unsigned).

    The wallet replaces the placeholder blockhash and signature before
    broadcast. We use :class:`NullSigner` to seat an empty signature in
    the right slot so the resulting bytes round-trip cleanly through
    ``VersionedTransaction.from_bytes`` on the wallet side.
    """

    message = MessageV0.try_compile(
        payer=payer,
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=_PLACEHOLDER_BLOCKHASH,
    )
    tx = VersionedTransaction(message, [NullSigner(payer)])
    return base64.b64encode(bytes(tx)).decode("ascii")


class SwapToDepositService:
    """Swap an arbitrary input token into the pool's mint, then deposit it.

    The two-tx flow is intentional. A single-tx flow would require the
    backend to either (a) custody the user's keys (terrible) or (b) chain
    the swap and deposit on-chain (would need a router program, out of
    hackathon scope). Returning two unsigned txs lets the wallet sign
    each one — same UX as Jupiter Lite + a follow-up tx.
    """

    def __init__(self, bags_client: BagsAPIClient) -> None:
        self._bags = bags_client

    async def build_chain(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_in: int,
        slippage_bps: int,
        depositor_pubkey: str,
        commitment_hex: str,
    ) -> dict[str, Any]:
        """Build (swap_tx, deposit_tx) ready for the wallet to sign in order.

        Returns a dict shaped:

            {
                "swap_tx": "<base64 unsigned tx>",
                "deposit_tx": "<base64 unsigned tx>",
                "swap_quote": {...},          # raw upstream payload
                "deposit_program_id": "<base58>",
                "deposit_token_mint": "<base58>",
            }

        The wallet MUST submit ``swap_tx`` first and wait for it to land
        before broadcasting ``deposit_tx`` — the deposit ix transfers
        ``output_mint`` out of the depositor's wallet, so it'll fail
        simulation if the swap hasn't settled yet.
        """

        if not settings.bagsvault_program_id:
            raise ServiceUnavailableError(
                "BAGSVAULT_PROGRAM_ID is not configured.",
                details={"missing_env": "BAGSVAULT_PROGRAM_ID"},
            )
        program_id = _decode_pubkey(
            settings.bagsvault_program_id, label="BAGSVAULT_PROGRAM_ID"
        )

        depositor = _decode_pubkey(depositor_pubkey, label="depositor_pubkey")
        token_mint = _decode_pubkey(output_mint, label="output_mint")
        commitment = _hex_to_bytes32(commitment_hex, label="commitment_hex")

        # 1. Fetch swap quote + unsigned tx from Bags.
        swap_raw = await self._bags.get_swap_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount_in,
            slippage_bps=slippage_bps,
        )
        swap_tx_b64 = _extract_swap_tx_b64(swap_raw)

        # 2. Build the deposit ix targeting the pool keyed on output_mint.
        deposit_ix = build_deposit_ix(
            program_id=program_id,
            token_mint=token_mint,
            depositor=depositor,
            commitment_bytes32=commitment,
        )
        deposit_tx_b64 = _serialize_unsigned_tx(deposit_ix, depositor)

        logger.info(
            "swap_to_deposit.build_chain in=%s out=%s amount=%d depositor=%s",
            input_mint,
            output_mint,
            amount_in,
            depositor_pubkey,
        )

        return {
            "swap_tx": swap_tx_b64,
            "deposit_tx": deposit_tx_b64,
            "swap_quote": swap_raw,
            "deposit_program_id": str(program_id),
            "deposit_token_mint": str(token_mint),
        }


__all__ = [
    "DEPOSIT_SIGHASH",
    "MERKLE_TREE_SEED",
    "VAULT_SEED",
    "SwapToDepositService",
    "build_deposit_ix",
]
