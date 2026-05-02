"""Tests for the deposit instruction builder.

These pin the on-chain ABI assumptions: any drift between the Rust
program and ``app.services.deposit_builder`` will surface as a failure
here, before it becomes an opaque "Custom program error: 0x101" on
devnet.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from app.config import settings
from app.exceptions import ServiceUnavailableError, ValidationError
from app.services.deposit_builder import (
    DEPOSIT_SIGHASH,
    DepositBuilder,
    MERKLE_TREE_SEED,
    SYSTEM_PROGRAM_ID,
    VAULT_SEED,
    _build_deposit_ix,
    _resolve_token_mint,
)


SYSTEM_PROGRAM = "11111111111111111111111111111111"


# ---------------------------------------------------------------------------
# Pure constants
# ---------------------------------------------------------------------------
def test_sighash_matches_anchor_global_deposit() -> None:
    """First 8 bytes of sha256("global:deposit") — the Anchor convention."""

    expected = hashlib.sha256(b"global:deposit").digest()[:8]
    assert DEPOSIT_SIGHASH == expected
    assert len(DEPOSIT_SIGHASH) == 8


def test_pda_seeds_match_program() -> None:
    """Pin the PDA seed strings — they're shared with the on-chain program."""

    assert MERKLE_TREE_SEED == b"merkle_tree"
    assert VAULT_SEED == b"vault"
    assert SYSTEM_PROGRAM_ID == "11111111111111111111111111111111"


# ---------------------------------------------------------------------------
# Token-mint resolver
# ---------------------------------------------------------------------------
def test_resolve_token_mint_sol_sentinel_returns_system_program() -> None:
    pk = _resolve_token_mint("SOL")
    assert str(pk) == SYSTEM_PROGRAM


def test_resolve_token_mint_empty_string_returns_system_program() -> None:
    pk = _resolve_token_mint("")
    assert str(pk) == SYSTEM_PROGRAM


def test_resolve_token_mint_invalid_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _resolve_token_mint("not-a-base58-pubkey!!!")


# ---------------------------------------------------------------------------
# Instruction shape
# ---------------------------------------------------------------------------
def test_build_deposit_ix_has_four_accounts_in_documented_order() -> None:
    program_id = Pubkey.from_string(SYSTEM_PROGRAM)
    depositor = Pubkey.from_string(SYSTEM_PROGRAM)
    vault = Pubkey.from_string(SYSTEM_PROGRAM)
    tree_state = Pubkey.from_string(SYSTEM_PROGRAM)

    ix = _build_deposit_ix(
        program_id=program_id,
        depositor=depositor,
        vault=vault,
        tree_state=tree_state,
        commitment=b"\x42" * 32,
    )

    assert len(ix.accounts) == 4
    # Account 0: depositor (signer + writable).
    assert ix.accounts[0].is_signer is True
    assert ix.accounts[0].is_writable is True
    # Account 1: vault PDA (writable).
    assert ix.accounts[1].is_signer is False
    assert ix.accounts[1].is_writable is True
    # Account 2: tree_state PDA (writable).
    assert ix.accounts[2].is_signer is False
    assert ix.accounts[2].is_writable is True
    # Account 3: system program (read-only).
    assert ix.accounts[3].is_signer is False
    assert ix.accounts[3].is_writable is False
    assert str(ix.accounts[3].pubkey) == SYSTEM_PROGRAM


def test_build_deposit_ix_data_layout_is_sighash_plus_commitment() -> None:
    program_id = Pubkey.from_string(SYSTEM_PROGRAM)
    commitment = bytes.fromhex("ab" * 32)

    ix = _build_deposit_ix(
        program_id=program_id,
        depositor=program_id,
        vault=program_id,
        tree_state=program_id,
        commitment=commitment,
    )

    assert len(ix.data) == 8 + 32
    assert ix.data[:8] == DEPOSIT_SIGHASH
    assert ix.data[8:] == commitment


def test_build_deposit_ix_rejects_short_commitment() -> None:
    program_id = Pubkey.from_string(SYSTEM_PROGRAM)
    with pytest.raises(ValidationError):
        _build_deposit_ix(
            program_id=program_id,
            depositor=program_id,
            vault=program_id,
            tree_state=program_id,
            commitment=b"\x00" * 16,  # too short
        )


# ---------------------------------------------------------------------------
# DepositBuilder integration
# ---------------------------------------------------------------------------
class _FakeRpc:
    def __init__(self, blockhash: Any = None) -> None:
        self.blockhash = blockhash or {
            "blockhash": "11111111111111111111111111111111",
            "lastValidBlockHeight": 1,
        }

    async def get_recent_blockhash(self) -> Any:
        return self.blockhash


@pytest.mark.asyncio
async def test_build_unsigned_tx_503_when_program_id_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", "")
    builder = DepositBuilder(rpc=_FakeRpc())
    with pytest.raises(ServiceUnavailableError):
        await builder.build_unsigned_tx(
            commitment_hex="00" * 32,
            amount_lamports=1_000_000_000,
            depositor=SYSTEM_PROGRAM,
        )


@pytest.mark.asyncio
async def test_build_unsigned_tx_returns_versioned_tx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", SYSTEM_PROGRAM)
    builder = DepositBuilder(rpc=_FakeRpc())

    out = await builder.build_unsigned_tx(
        commitment_hex="ab" * 32,
        amount_lamports=1_000_000_000,
        depositor=SYSTEM_PROGRAM,
    )

    assert "tx_base64" in out
    assert out["program_id"] == SYSTEM_PROGRAM
    assert out["commitment"] == "ab" * 32
    assert out["amount"] == 1_000_000_000
    assert out["token"] == "SOL"

    # The base64 should round-trip into a real VersionedTransaction whose
    # only ix carries our deposit sighash.
    tx_bytes = base64.b64decode(out["tx_base64"])
    tx = VersionedTransaction.from_bytes(tx_bytes)
    msg = tx.message
    assert len(msg.instructions) == 1
    ix = msg.instructions[0]
    assert bytes(ix.data)[:8] == DEPOSIT_SIGHASH
    assert bytes(ix.data)[8:] == bytes.fromhex("ab" * 32)


@pytest.mark.asyncio
async def test_build_unsigned_tx_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "bagsvault_program_id", SYSTEM_PROGRAM)
    builder = DepositBuilder(rpc=_FakeRpc())
    with pytest.raises(ValidationError):
        await builder.build_unsigned_tx(
            commitment_hex="00" * 32,
            amount_lamports=1,
            depositor=SYSTEM_PROGRAM,
            token_mint="not-a-pubkey",
        )
