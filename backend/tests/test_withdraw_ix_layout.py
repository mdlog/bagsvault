"""Unit tests for the Phase 4 Anchor-aligned withdraw ix builder.

The on-chain program's account ordering and instruction-data layout are
load-bearing: a mismatch produces an opaque deserialisation error from
the Anchor framework. These tests pin the wire format so future
refactors fail loudly instead of silently shifting the layout.

Scope note: the ix data layout itself does NOT include ``fee_bps`` —
the on-chain handler reads ``tree_state.relayer_fee_bps`` directly when
assembling the public-input array passed to the verifier. The
public-input layout is verified separately in
:mod:`tests.test_relayer_fee_layout` and :mod:`tests.test_zk_proof_service`.
"""

from __future__ import annotations

import hashlib

from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID

from app.services.withdrawal_service import (
    MERKLE_TREE_SEED,
    NULLIFIER_SEED,
    VAULT_SEED,
    WITHDRAW_SIGHASH,
    _build_withdraw_ix,
    _resolve_token_mint,
)


PROGRAM_ID = Pubkey.from_string("AXEc2HCqETrPqzdG8AkErLxfNXDHyeH4cwykvX6qxXvJ")


def test_withdraw_sighash_matches_anchor_naming() -> None:
    """Sighash MUST equal SHA-256("global:withdraw")[..8].

    Anchor derives the per-instruction sighash from `global:<fn_name>`.
    If the program ever renames `withdraw`, the on-chain ix won't
    deserialise — this test catches the drift on the backend side.
    """

    expected = hashlib.sha256(b"global:withdraw").digest()[:8]
    assert WITHDRAW_SIGHASH == expected
    assert len(WITHDRAW_SIGHASH) == 8


def test_resolve_token_mint_sentinels() -> None:
    """SOL pool resolves to the System Program; arbitrary mint passes through."""

    assert _resolve_token_mint("SOL") == SYSTEM_PROGRAM_ID
    assert _resolve_token_mint("") == SYSTEM_PROGRAM_ID
    explicit = "11111111111111111111111111111112"  # any other base58 32-byte
    assert _resolve_token_mint(explicit) == Pubkey.from_string(explicit)


def test_build_withdraw_ix_account_ordering() -> None:
    """Accounts must follow `instructions/withdraw.rs::Withdraw` exactly."""

    relayer = Pubkey.from_string("11111111111111111111111111111113")
    recipient = Pubkey.from_string("11111111111111111111111111111114")
    nullifier = b"\x11" * 32
    proof = b"\x00" * 256
    root = b"\xab" * 32

    ix = _build_withdraw_ix(
        program_id=PROGRAM_ID,
        token_mint=SYSTEM_PROGRAM_ID,
        recipient=recipient,
        relayer=relayer,
        proof_bytes=proof,
        root_bytes=root,
        nullifier_bytes=nullifier,
        amount=1_000_000_000,
    )

    assert ix.program_id == PROGRAM_ID
    accounts = list(ix.accounts)
    assert len(accounts) == 6

    # 0. relayer (signer + writable)
    assert accounts[0].pubkey == relayer
    assert accounts[0].is_signer is True
    assert accounts[0].is_writable is True

    # 1. vault PDA
    expected_vault, _ = Pubkey.find_program_address(
        [VAULT_SEED, bytes(SYSTEM_PROGRAM_ID)], PROGRAM_ID
    )
    assert accounts[1].pubkey == expected_vault
    assert accounts[1].is_writable is True

    # 2. tree_state PDA
    expected_tree, _ = Pubkey.find_program_address(
        [MERKLE_TREE_SEED, bytes(SYSTEM_PROGRAM_ID)], PROGRAM_ID
    )
    assert accounts[2].pubkey == expected_tree
    assert accounts[2].is_writable is True

    # 3. nullifier PDA
    expected_null, _ = Pubkey.find_program_address(
        [NULLIFIER_SEED, nullifier], PROGRAM_ID
    )
    assert accounts[3].pubkey == expected_null
    assert accounts[3].is_writable is True

    # 4. recipient (writable)
    assert accounts[4].pubkey == recipient
    assert accounts[4].is_writable is True

    # 5. system_program (read-only)
    assert accounts[5].pubkey == SYSTEM_PROGRAM_ID
    assert accounts[5].is_signer is False
    assert accounts[5].is_writable is False


def test_build_withdraw_ix_data_layout() -> None:
    """Instruction data: sighash | proof_len(u32 LE) | proof | root | null | recipient | amount."""

    relayer = Pubkey.from_string("11111111111111111111111111111113")
    recipient = Pubkey.from_string("11111111111111111111111111111114")
    proof = bytes(range(64)) * 4  # 256 bytes
    root = b"\xab" * 32
    nullifier = b"\x11" * 32
    amount = 1_000_000_000

    ix = _build_withdraw_ix(
        program_id=PROGRAM_ID,
        token_mint=SYSTEM_PROGRAM_ID,
        recipient=recipient,
        relayer=relayer,
        proof_bytes=proof,
        root_bytes=root,
        nullifier_bytes=nullifier,
        amount=amount,
    )

    data = bytes(ix.data)
    # sighash (8)
    assert data[0:8] == WITHDRAW_SIGHASH
    # proof_len u32 LE (4)
    assert int.from_bytes(data[8:12], "little") == len(proof)
    # proof bytes
    assert data[12 : 12 + len(proof)] == proof
    cursor = 12 + len(proof)
    # root (32)
    assert data[cursor : cursor + 32] == root
    cursor += 32
    # nullifier (32)
    assert data[cursor : cursor + 32] == nullifier
    cursor += 32
    # recipient pubkey (32)
    assert data[cursor : cursor + 32] == bytes(recipient)
    cursor += 32
    # amount u64 LE (8)
    assert int.from_bytes(data[cursor : cursor + 8], "little") == amount
    assert len(data) == cursor + 8


def test_build_withdraw_ix_left_pads_short_root_and_nullifier() -> None:
    """Operator-supplied hex may strip leading zeros — left-pad to 32 bytes."""

    short_root = b"\xff"  # 1 byte
    short_null = b"\x01\x02\x03"
    ix = _build_withdraw_ix(
        program_id=PROGRAM_ID,
        token_mint=SYSTEM_PROGRAM_ID,
        recipient=Pubkey.from_string("11111111111111111111111111111114"),
        relayer=Pubkey.from_string("11111111111111111111111111111113"),
        proof_bytes=b"\x00" * 256,
        root_bytes=short_root,
        nullifier_bytes=short_null,
        amount=1,
    )
    data = bytes(ix.data)
    proof_end = 12 + 256
    root32 = data[proof_end : proof_end + 32]
    null32 = data[proof_end + 32 : proof_end + 64]
    assert root32 == b"\x00" * 31 + b"\xff"
    assert null32 == b"\x00" * 29 + b"\x01\x02\x03"
