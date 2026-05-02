"""Wire-format tests for the SPL withdraw ix builder.

These pin the sighash, account ordering, and instruction-data layout of
``withdraw_spl`` against ``programs/bagsvault/src/instructions/withdraw.rs::WithdrawSpl``.
A drift between the two will surface as an Anchor deserialisation error
on-chain — these tests catch it on the backend side first.
"""

from __future__ import annotations

import hashlib

from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID

from app.services.withdrawal_service import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    MERKLE_TREE_SEED,
    NULLIFIER_SEED,
    SPL_TOKEN_PROGRAM_ID,
    VAULT_SEED,
    WITHDRAW_SPL_SIGHASH,
    _build_withdraw_spl_ix,
    _derive_ata,
)


PROGRAM_ID = Pubkey.from_string("AXEc2HCqETrPqzdG8AkErLxfNXDHyeH4cwykvX6qxXvJ")
TOKEN_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")  # any non-system mint


def test_withdraw_spl_sighash_matches_anchor_naming() -> None:
    """Sighash MUST equal SHA-256("global:withdraw_spl")[..8]."""

    expected = hashlib.sha256(b"global:withdraw_spl").digest()[:8]
    assert WITHDRAW_SPL_SIGHASH == expected
    assert len(WITHDRAW_SPL_SIGHASH) == 8


def test_spl_program_constants_pinned() -> None:
    """Token + ATA program IDs must match Solana's canonical values."""

    assert str(SPL_TOKEN_PROGRAM_ID) == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    assert str(ASSOCIATED_TOKEN_PROGRAM_ID) == "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"


def test_derive_ata_matches_canonical_seeds() -> None:
    """ATA derivation seeds must be ``[owner, TOKEN_PROGRAM, mint]``."""

    owner = Pubkey.from_string("11111111111111111111111111111114")
    expected, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(SPL_TOKEN_PROGRAM_ID), bytes(TOKEN_MINT)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    assert _derive_ata(owner, TOKEN_MINT) == expected


def test_build_withdraw_spl_ix_account_ordering() -> None:
    """Accounts must follow ``WithdrawSpl`` in withdraw.rs exactly."""

    relayer = Pubkey.from_string("11111111111111111111111111111113")
    recipient = Pubkey.from_string("11111111111111111111111111111114")
    nullifier = b"\x22" * 32
    proof = b"\x00" * 256
    root = b"\xab" * 32

    ix = _build_withdraw_spl_ix(
        program_id=PROGRAM_ID,
        token_mint=TOKEN_MINT,
        recipient=recipient,
        relayer=relayer,
        proof_bytes=proof,
        root_bytes=root,
        nullifier_bytes=nullifier,
        amount=1_000_000_000,
    )

    assert ix.program_id == PROGRAM_ID
    accounts = list(ix.accounts)
    # 0 relayer | 1 vault | 2 vault_ata | 3 tree_state | 4 nullifier
    # 5 recipient | 6 recipient_ata | 7 token_program | 8 system_program
    assert len(accounts) == 9

    # 0. relayer
    assert accounts[0].pubkey == relayer
    assert accounts[0].is_signer is True
    assert accounts[0].is_writable is True

    # 1. vault PDA
    expected_vault, _ = Pubkey.find_program_address(
        [VAULT_SEED, bytes(TOKEN_MINT)], PROGRAM_ID
    )
    assert accounts[1].pubkey == expected_vault
    assert accounts[1].is_writable is True
    assert accounts[1].is_signer is False

    # 2. vault ATA
    expected_vault_ata = _derive_ata(expected_vault, TOKEN_MINT)
    assert accounts[2].pubkey == expected_vault_ata
    assert accounts[2].is_writable is True

    # 3. tree_state PDA
    expected_tree, _ = Pubkey.find_program_address(
        [MERKLE_TREE_SEED, bytes(TOKEN_MINT)], PROGRAM_ID
    )
    assert accounts[3].pubkey == expected_tree
    assert accounts[3].is_writable is True

    # 4. nullifier PDA
    expected_null, _ = Pubkey.find_program_address(
        [NULLIFIER_SEED, nullifier], PROGRAM_ID
    )
    assert accounts[4].pubkey == expected_null
    assert accounts[4].is_writable is True

    # 5. recipient (read-only — pinned by `address = recipient`)
    assert accounts[5].pubkey == recipient
    assert accounts[5].is_writable is False
    assert accounts[5].is_signer is False

    # 6. recipient ATA
    expected_recipient_ata = _derive_ata(recipient, TOKEN_MINT)
    assert accounts[6].pubkey == expected_recipient_ata
    assert accounts[6].is_writable is True

    # 7. token_program
    assert accounts[7].pubkey == SPL_TOKEN_PROGRAM_ID
    assert accounts[7].is_writable is False
    assert accounts[7].is_signer is False

    # 8. system_program
    assert accounts[8].pubkey == SYSTEM_PROGRAM_ID
    assert accounts[8].is_writable is False
    assert accounts[8].is_signer is False


def test_build_withdraw_spl_ix_data_layout_matches_sol_variant() -> None:
    """Same Borsh layout as the SOL ix; only the sighash differs."""

    relayer = Pubkey.from_string("11111111111111111111111111111113")
    recipient = Pubkey.from_string("11111111111111111111111111111114")
    proof = bytes(range(64)) * 4  # 256 bytes
    root = b"\xab" * 32
    nullifier = b"\x22" * 32
    amount = 1_000_000_000

    ix = _build_withdraw_spl_ix(
        program_id=PROGRAM_ID,
        token_mint=TOKEN_MINT,
        recipient=recipient,
        relayer=relayer,
        proof_bytes=proof,
        root_bytes=root,
        nullifier_bytes=nullifier,
        amount=amount,
    )

    data = bytes(ix.data)
    # sighash (8) — SPL-specific
    assert data[0:8] == WITHDRAW_SPL_SIGHASH
    # proof_len u32 LE (4)
    assert int.from_bytes(data[8:12], "little") == len(proof)
    assert data[12 : 12 + len(proof)] == proof
    cursor = 12 + len(proof)
    # root (32)
    assert data[cursor : cursor + 32] == root
    cursor += 32
    # nullifier (32)
    assert data[cursor : cursor + 32] == nullifier
    cursor += 32
    # recipient (32)
    assert data[cursor : cursor + 32] == bytes(recipient)
    cursor += 32
    # amount u64 LE (8)
    assert int.from_bytes(data[cursor : cursor + 8], "little") == amount
    assert len(data) == cursor + 8
