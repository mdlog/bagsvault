"""Pin the public-input layout that binds ``relayer_fee_bps`` into the proof.

The on-chain handler in ``programs/bagsvault/src/instructions/withdraw.rs``
appends ``u64_to_field(tree_state.relayer_fee_bps as u64)`` to the
public-input array at index 5. Three layers must agree on this:

* the Noir circuit (``circuits/bagsvault_withdraw/src/main.nr``),
* the on-chain verifier (``programs/bagsvault/src/verifier.rs``), and
* the off-chain prover (``backend/app/services/zk_proof_service.py``).

This test only covers the off-chain prover — it's the layer the backend
controls. A drift here would silently break verification on chain.
"""

from __future__ import annotations

import hashlib

import pytest
from solders.pubkey import Pubkey

from app.services.zk_proof_service import (
    BN254_R,
    WithdrawProofInput,
    ZkProofService,
    reset_zk_proof_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_zk_proof_service()
    yield
    reset_zk_proof_service()


def _u64_to_field_hex(value: int) -> str:
    """Mirror the on-chain ``verifier::u64_to_field`` helper."""

    return "0x" + value.to_bytes(32, "big").hex()


def _make_input(fee_bps: int) -> WithdrawProofInput:
    return WithdrawProofInput(
        nullifier=42,
        secret=137,
        amount=1_000_000_000,
        leaf_index=3,
        merkle_path=[0] * 20,
        is_left=[1] * 20,
        recipient_pubkey_bytes=bytes(Pubkey.default()),
        relayer_pubkey_bytes=hashlib.sha256(b"relayer").digest(),
        fee_bps=fee_bps,
    )


@pytest.mark.asyncio
async def test_public_input_count_is_six() -> None:
    """NUM_PUBLIC_INPUTS = 6 — root, nullifier, recipient, amount, relayer, fee_bps."""

    svc = ZkProofService(stub_mode=True)
    result = await svc.generate_withdraw_proof(_make_input(15))
    assert len(result.public_inputs_hex) == 6


@pytest.mark.asyncio
async def test_fee_bps_is_index_5_and_u64_to_field_encoded() -> None:
    """fee_bps lands at index 5, encoded as the on-chain ``u64_to_field``."""

    svc = ZkProofService(stub_mode=True)
    for fee_bps in (0, 15, 250, 1000):
        result = await svc.generate_withdraw_proof(_make_input(fee_bps))
        assert result.public_inputs_hex[5] == _u64_to_field_hex(fee_bps)


@pytest.mark.asyncio
async def test_other_public_inputs_unchanged_when_fee_bps_changes() -> None:
    """Only index 5 should move when fee_bps moves — all other slots stay put."""

    svc = ZkProofService(stub_mode=True)
    a = await svc.generate_withdraw_proof(_make_input(15))
    b = await svc.generate_withdraw_proof(_make_input(250))
    assert a.public_inputs_hex[:5] == b.public_inputs_hex[:5]
    assert a.public_inputs_hex[5] != b.public_inputs_hex[5]


@pytest.mark.asyncio
async def test_fee_bps_field_element_in_range() -> None:
    """Even ``fee_bps == 10000`` must reduce cleanly under the BN254 modulus."""

    svc = ZkProofService(stub_mode=True)
    result = await svc.generate_withdraw_proof(_make_input(10_000))
    assert int(result.public_inputs_hex[5], 16) == 10_000
    assert int(result.public_inputs_hex[5], 16) < BN254_R
