"""Tests for :mod:`app.clients.solana_signer`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from app.clients.solana_signer import SolanaSignerClient
from app.exceptions import ServiceUnavailableError


@pytest.fixture
def relayer_keypair_file(tmp_path: Path) -> Path:
    """Write a fresh Solana JSON keypair file to a tmp dir."""

    kp = Keypair()
    path = tmp_path / "relayer.json"
    path.write_text(json.dumps(list(bytes(kp))))
    return path


def test_signer_loads_keypair_and_returns_pubkey(relayer_keypair_file: Path) -> None:
    signer = SolanaSignerClient(keypair_path=relayer_keypair_file)
    pubkey = signer.pubkey()
    assert isinstance(pubkey, str)
    # Solana base58 pubkeys are 32-44 chars.
    assert 32 <= len(pubkey) <= 44
    # And the pubkey_obj helper returns the same value as a Pubkey.
    assert str(signer.pubkey_obj()) == pubkey


def test_signer_raises_on_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    signer = SolanaSignerClient(keypair_path=missing)
    with pytest.raises(ServiceUnavailableError) as ei:
        signer.pubkey()
    assert "Relayer keypair not configured" in ei.value.message
    assert ei.value.details["missing_path"] == str(missing)


def test_signer_raises_on_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not-json{")
    signer = SolanaSignerClient(keypair_path=path)
    with pytest.raises(ServiceUnavailableError):
        signer.pubkey()


def test_signer_raises_on_non_array_json(tmp_path: Path) -> None:
    path = tmp_path / "obj.json"
    path.write_text(json.dumps({"secret": [1, 2, 3]}))
    signer = SolanaSignerClient(keypair_path=path)
    with pytest.raises(ServiceUnavailableError):
        signer.pubkey()


def test_signer_raises_on_wrong_length_array(tmp_path: Path) -> None:
    path = tmp_path / "short.json"
    path.write_text(json.dumps([1, 2, 3]))
    signer = SolanaSignerClient(keypair_path=path)
    with pytest.raises(ServiceUnavailableError):
        signer.pubkey()


def test_signer_build_and_sign_returns_signed_versioned_tx(
    relayer_keypair_file: Path,
) -> None:
    signer = SolanaSignerClient(keypair_path=relayer_keypair_file)
    relayer_pubkey = signer.pubkey_obj()

    ix = Instruction(
        program_id=Pubkey.default(),
        accounts=[AccountMeta(pubkey=relayer_pubkey, is_signer=True, is_writable=True)],
        data=b"hello",
    )
    blockhash_b58 = str(Hash.default())
    signed = signer.build_and_sign(instructions=[ix], recent_blockhash=blockhash_b58)

    # Should round-trip back through solders as a real VersionedTransaction.
    tx = VersionedTransaction.from_bytes(signed)
    assert len(tx.signatures) >= 1
    # And the signing pubkey is the relayer.
    assert tx.message.account_keys[0] == relayer_pubkey


def test_signer_build_and_sign_raises_on_bad_blockhash(relayer_keypair_file: Path) -> None:
    signer = SolanaSignerClient(keypair_path=relayer_keypair_file)
    with pytest.raises(ServiceUnavailableError):
        signer.build_and_sign(instructions=[], recent_blockhash="not-a-real-blockhash")


def test_sign_transaction_accepts_versioned_tx(relayer_keypair_file: Path) -> None:
    """``sign_transaction`` re-builds with the relayer's signature attached."""

    signer = SolanaSignerClient(keypair_path=relayer_keypair_file)
    relayer_pubkey = signer.pubkey_obj()

    ix = Instruction(
        program_id=Pubkey.default(),
        accounts=[AccountMeta(pubkey=relayer_pubkey, is_signer=True, is_writable=True)],
        data=b"x",
    )
    unsigned_bytes = signer.build_and_sign(instructions=[ix], recent_blockhash=str(Hash.default()))
    unsigned = VersionedTransaction.from_bytes(unsigned_bytes)
    re_signed = signer.sign_transaction(unsigned)
    tx = VersionedTransaction.from_bytes(re_signed)
    assert tx.message.account_keys[0] == relayer_pubkey
