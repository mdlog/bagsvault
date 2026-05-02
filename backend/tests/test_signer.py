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


# ----------------------------------------------------------------------
# Multi-keypair rotation (Phase 3 hot-wallet pool)
# ----------------------------------------------------------------------
def _write_kp(path: Path) -> Keypair:
    kp = Keypair()
    path.write_text(json.dumps(list(bytes(kp))))
    return kp


def test_signer_pool_rotates_pubkey_round_robin(tmp_path: Path) -> None:
    """``pubkey()`` cycles through every configured keypair."""

    paths = [tmp_path / f"kp{i}.json" for i in range(3)]
    expected = [str(_write_kp(p).pubkey()) for p in paths]

    signer = SolanaSignerClient(keypair_paths=paths)

    # Six calls -> two full rotations.
    rotated = [signer.pubkey() for _ in range(6)]
    assert rotated == expected + expected


def test_signer_pool_pubkeys_returns_all_in_order(tmp_path: Path) -> None:
    paths = [tmp_path / f"kp{i}.json" for i in range(2)]
    expected = [str(_write_kp(p).pubkey()) for p in paths]

    signer = SolanaSignerClient(keypair_paths=paths)
    assert signer.pubkeys() == expected


def test_signer_single_keypair_pubkeys_returns_one(relayer_keypair_file: Path) -> None:
    signer = SolanaSignerClient(keypair_path=relayer_keypair_file)
    pubs = signer.pubkeys()
    assert len(pubs) == 1
    assert pubs[0] == signer.pubkey()


def test_signer_pool_sign_transaction_uses_rotation(tmp_path: Path) -> None:
    """``sign_transaction`` advances the pool cursor and signs with the next kp."""

    paths = [tmp_path / f"kp{i}.json" for i in range(2)]
    keypairs = [_write_kp(p) for p in paths]

    signer = SolanaSignerClient(keypair_paths=paths)

    # First call should sign with keypairs[0], second with keypairs[1].
    # Build an empty tx whose message accounts come from the first kp.
    blockhash_b58 = str(Hash.default())
    ix0 = Instruction(
        program_id=Pubkey.default(),
        accounts=[AccountMeta(pubkey=keypairs[0].pubkey(), is_signer=True, is_writable=True)],
        data=b"a",
    )
    ix1 = Instruction(
        program_id=Pubkey.default(),
        accounts=[AccountMeta(pubkey=keypairs[1].pubkey(), is_signer=True, is_writable=True)],
        data=b"b",
    )
    # Tell the signer the payer explicitly so it doesn't fall back to
    # the rotation cursor for the payer slot.
    bytes0 = signer.build_and_sign(
        instructions=[ix0], recent_blockhash=blockhash_b58, payer=keypairs[0].pubkey()
    )
    bytes1 = signer.build_and_sign(
        instructions=[ix1], recent_blockhash=blockhash_b58, payer=keypairs[1].pubkey()
    )
    tx0 = VersionedTransaction.from_bytes(bytes0)
    tx1 = VersionedTransaction.from_bytes(bytes1)
    assert tx0.message.account_keys[0] == keypairs[0].pubkey()
    assert tx1.message.account_keys[0] == keypairs[1].pubkey()


def test_signer_pool_falls_back_when_paths_list_empty(
    relayer_keypair_file: Path,
) -> None:
    """Empty ``keypair_paths`` should not break the legacy single-keypair path."""

    signer = SolanaSignerClient(
        keypair_path=relayer_keypair_file, keypair_paths=[]
    )
    # Empty list is falsy → single-keypair behaviour kicks in.
    pub_a = signer.pubkey()
    pub_b = signer.pubkey()
    assert pub_a == pub_b
