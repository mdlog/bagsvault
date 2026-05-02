"""Tests for the Phase 4 ZK proof generator service.

These tests run without `nargo` / `bb` installed — the service degrades
to stub mode when the toolchain is missing, which is exactly what we
exercise here. The stub proof is rejected on-chain by design, so any
test that requires a real proof should run inside an integration suite
with the real toolchain on PATH.
"""

from __future__ import annotations

import hashlib

import pytest
from solders.pubkey import Pubkey

from app.services.zk_proof_service import (
    BN254_R,
    PoseidonHasher,
    WithdrawProofInput,
    ZkProofService,
    reset_zk_proof_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_zk_proof_service()
    yield
    reset_zk_proof_service()


def _service(stub: bool = True) -> ZkProofService:
    return ZkProofService(stub_mode=stub)


def test_commitment_is_deterministic_and_in_field() -> None:
    svc = _service()
    a = svc.commitment(nullifier=1, secret=2, amount=10)
    b = svc.commitment(nullifier=1, secret=2, amount=10)
    assert a == b
    assert 0 <= a < BN254_R


def test_commitment_changes_when_inputs_change() -> None:
    svc = _service()
    base = svc.commitment(nullifier=1, secret=2, amount=10)
    # Each variation should yield a different leaf.
    assert svc.commitment(nullifier=2, secret=2, amount=10) != base
    assert svc.commitment(nullifier=1, secret=3, amount=10) != base
    assert svc.commitment(nullifier=1, secret=2, amount=11) != base


def test_nullifier_hash_unique_per_leaf_index() -> None:
    svc = _service()
    h0 = svc.nullifier_hash(nullifier=42, leaf_index=0)
    h1 = svc.nullifier_hash(nullifier=42, leaf_index=1)
    assert h0 != h1


def test_merkle_root_walk_matches_self_consistency() -> None:
    """Walking with `is_left=1` everywhere uses each level's right sibling=0.

    We don't assert a specific value (depends on Poseidon backend); we
    only assert the function is deterministic and walks the full path.
    """

    svc = _service()
    leaf = svc.commitment(1, 2, 3)
    path = [0] * 20
    is_left = [1] * 20
    r1 = svc.merkle_root_from_path(leaf, path, is_left)
    r2 = svc.merkle_root_from_path(leaf, path, is_left)
    assert r1 == r2
    # Flipping a single sibling must change the root.
    bumped = svc.merkle_root_from_path(leaf, [1] + [0] * 19, is_left)
    assert bumped != r1


def test_merkle_root_rejects_uneven_witness_lengths() -> None:
    svc = _service()
    with pytest.raises(ValueError):
        svc.merkle_root_from_path(0, [0, 0], [1])


@pytest.mark.asyncio
async def test_stub_mode_returns_zero_proof_and_correct_public_inputs() -> None:
    svc = _service(stub=True)
    recipient = bytes(Pubkey.default())
    relayer = hashlib.sha256(b"relayer").digest()
    inp = WithdrawProofInput(
        nullifier=7,
        secret=11,
        amount=1_000_000_000,
        leaf_index=0,
        merkle_path=[0] * 20,
        is_left=[1] * 20,
        recipient_pubkey_bytes=recipient,
        relayer_pubkey_bytes=relayer,
        fee_bps=15,
    )
    result = await svc.generate_withdraw_proof(inp)

    # Stub proofs are 256 bytes of zeros; they must be the right size so
    # `programs/bagsvault/src/verifier.rs::verify_withdraw_proof`'s
    # length precondition is exercised even on stub-mode failure paths.
    assert result.proof_hex.startswith("0x")
    assert len(result.proof_hex) == 2 + 256 * 2
    assert all(c == "0" for c in result.proof_hex[2:])

    # Public-input vector ordering must match the on-chain verifier.
    # NUM_PUBLIC_INPUTS = 6 with fee_bps at index 5.
    assert len(result.public_inputs_hex) == 6
    assert result.public_inputs_hex[0] == result.root_hex
    assert result.public_inputs_hex[1] == result.nullifier_hash_hex
    # amount is encoded as a 32-byte BE field element.
    assert result.public_inputs_hex[3].endswith(
        (1_000_000_000).to_bytes(8, "big").hex()
    )
    # fee_bps lives at index 5, encoded as a u64 BE field element so the
    # last 8 bytes carry 15 = 0x0f and everything else is zero.
    fee_hex = result.public_inputs_hex[5]
    assert fee_hex.startswith("0x")
    assert fee_hex.endswith((15).to_bytes(8, "big").hex())
    assert int(fee_hex, 16) == 15


@pytest.mark.asyncio
async def test_fee_bps_at_index_5_changes_with_input() -> None:
    """Pin the public-input ordering: fee_bps lives at index 5 and only
    that slot changes when fee_bps changes."""

    svc = _service(stub=True)
    recipient = bytes(Pubkey.default())
    relayer = hashlib.sha256(b"relayer").digest()

    def _make(fee: int) -> WithdrawProofInput:
        return WithdrawProofInput(
            nullifier=7,
            secret=11,
            amount=1_000_000_000,
            leaf_index=0,
            merkle_path=[0] * 20,
            is_left=[1] * 20,
            recipient_pubkey_bytes=recipient,
            relayer_pubkey_bytes=relayer,
            fee_bps=fee,
        )

    a = await svc.generate_withdraw_proof(_make(15))
    b = await svc.generate_withdraw_proof(_make(250))

    assert a.public_inputs_hex[:5] == b.public_inputs_hex[:5]
    assert a.public_inputs_hex[5] != b.public_inputs_hex[5]
    assert int(b.public_inputs_hex[5], 16) == 250


def test_toolchain_probe_does_not_raise_when_binaries_missing() -> None:
    svc = ZkProofService(nargo_bin="this-bin-does-not-exist-xyz", bb_bin="nope-xyz")
    assert svc._toolchain_available() is False  # noqa: SLF001 — internal probe


def test_poseidon_hasher_select_backend_is_deterministic() -> None:
    """The fallback backend (sha256-based) must hash inputs deterministically."""

    h = PoseidonHasher()
    assert h.hash([1, 2, 3]) == h.hash([1, 2, 3])
    # Field reduction enforces results below the BN254 modulus.
    assert h.hash([1, 2, 3]) < BN254_R
