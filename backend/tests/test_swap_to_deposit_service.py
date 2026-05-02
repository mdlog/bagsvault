"""Tests for the swap-then-deposit chained orchestrator.

The service must:

1. Pull the unsigned swap tx from the Bags API verbatim, regardless of
   which key the upstream payload uses to expose it.
2. Build a valid Anchor ``deposit(commitment)`` ix targeting the pool
   keyed on ``output_mint`` and serialise it as a base64 unsigned
   versioned transaction whose payer is the depositor.
3. Return BOTH artefacts in a stable shape and never sign or broadcast.

We fake the :class:`BagsAPIClient` to keep the test fully offline.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction

from app.config import settings
from app.exceptions import ServiceUnavailableError
from app.services.swap_to_deposit_service import (
    DEPOSIT_SIGHASH,
    MERKLE_TREE_SEED,
    VAULT_SEED,
    SwapToDepositService,
    build_deposit_ix,
)


PROGRAM_ID_STR = "AXEc2HCqETrPqzdG8AkErLxfNXDHyeH4cwykvX6qxXvJ"
DEPOSITOR_STR = "11111111111111111111111111111114"
OUTPUT_MINT_STR = "11111111111111111111111111111115"
COMMITMENT_HEX = "0x" + ("ab" * 32)


class _FakeBagsClient:
    """Minimal stand-in for :class:`BagsAPIClient`."""

    def __init__(self, swap_response: dict) -> None:
        self._swap_response = swap_response
        self.last_call: dict | None = None

    async def get_swap_quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> dict:
        self.last_call = {
            "input_mint": input_mint,
            "output_mint": output_mint,
            "amount": amount,
            "slippage_bps": slippage_bps,
        }
        return self._swap_response


@pytest.fixture(autouse=True)
def _set_program_id() -> None:
    original = settings.bagsvault_program_id
    settings.bagsvault_program_id = PROGRAM_ID_STR
    yield
    settings.bagsvault_program_id = original


def test_deposit_sighash_matches_anchor_naming() -> None:
    """The deposit sighash MUST equal SHA-256("global:deposit")[..8]."""

    expected = hashlib.sha256(b"global:deposit").digest()[:8]
    assert DEPOSIT_SIGHASH == expected
    assert len(DEPOSIT_SIGHASH) == 8


def test_build_deposit_ix_account_ordering_and_data() -> None:
    program_id = Pubkey.from_string(PROGRAM_ID_STR)
    depositor = Pubkey.from_string(DEPOSITOR_STR)
    token_mint = Pubkey.from_string(OUTPUT_MINT_STR)
    commitment = b"\xab" * 32

    ix = build_deposit_ix(
        program_id=program_id,
        token_mint=token_mint,
        depositor=depositor,
        commitment_bytes32=commitment,
    )

    assert ix.program_id == program_id
    accounts = list(ix.accounts)
    assert len(accounts) == 4
    # 0. depositor (signer + writable)
    assert accounts[0].pubkey == depositor
    assert accounts[0].is_signer is True
    assert accounts[0].is_writable is True
    # 1. vault PDA
    expected_vault, _ = Pubkey.find_program_address(
        [VAULT_SEED, bytes(token_mint)], program_id
    )
    assert accounts[1].pubkey == expected_vault
    assert accounts[1].is_writable is True
    # 2. tree_state PDA
    expected_tree, _ = Pubkey.find_program_address(
        [MERKLE_TREE_SEED, bytes(token_mint)], program_id
    )
    assert accounts[2].pubkey == expected_tree
    assert accounts[2].is_writable is True
    # 3. system_program (read-only)
    assert accounts[3].pubkey == SYSTEM_PROGRAM_ID
    assert accounts[3].is_signer is False
    assert accounts[3].is_writable is False

    # Data: sighash(8) | commitment(32) — fixed-length array, no len prefix.
    data = bytes(ix.data)
    assert len(data) == 8 + 32
    assert data[0:8] == DEPOSIT_SIGHASH
    assert data[8:40] == commitment


@pytest.mark.asyncio
async def test_build_chain_returns_both_unsigned_txs_and_quote() -> None:
    swap_b64 = base64.b64encode(b"\x01\x02\x03").decode("ascii")
    fake = _FakeBagsClient({"transaction": swap_b64, "route": {"hops": 2}})
    svc = SwapToDepositService(bags_client=fake)

    result = await svc.build_chain(
        input_mint=OUTPUT_MINT_STR,
        output_mint=OUTPUT_MINT_STR,
        amount_in=1_000_000_000,
        slippage_bps=75,
        depositor_pubkey=DEPOSITOR_STR,
        commitment_hex=COMMITMENT_HEX,
    )

    # Shape pin: both txs are present, both are base64 strings.
    assert set(result.keys()) == {
        "swap_tx",
        "deposit_tx",
        "swap_quote",
        "deposit_program_id",
        "deposit_token_mint",
    }
    assert isinstance(result["swap_tx"], str)
    assert isinstance(result["deposit_tx"], str)
    # Swap tx is forwarded verbatim (no re-encoding).
    assert result["swap_tx"] == swap_b64
    # Quote payload is forwarded for inspection.
    assert result["swap_quote"]["route"] == {"hops": 2}
    # Program id + token mint are echoed back canonicalised.
    assert result["deposit_program_id"] == PROGRAM_ID_STR
    assert result["deposit_token_mint"] == OUTPUT_MINT_STR

    # The upstream client was called with the same inputs.
    assert fake.last_call == {
        "input_mint": OUTPUT_MINT_STR,
        "output_mint": OUTPUT_MINT_STR,
        "amount": 1_000_000_000,
        "slippage_bps": 75,
    }

    # The deposit tx must round-trip through VersionedTransaction.
    raw = base64.b64decode(result["deposit_tx"])
    tx = VersionedTransaction.from_bytes(raw)
    # Single-ix message — the deposit ix is the only one.
    assert len(tx.message.instructions) == 1


@pytest.mark.asyncio
async def test_build_chain_handles_alternate_swap_response_shapes() -> None:
    """Bags may carry the unsigned swap tx under any of several keys."""

    swap_b64 = "ZHVtbXktdHg="  # "dummy-tx" base64'd.
    for shape in [
        {"transaction": swap_b64},
        {"swapTransaction": swap_b64},
        {"transactions": [swap_b64]},
        {"data": {"transaction": swap_b64}},
    ]:
        fake = _FakeBagsClient(shape)
        svc = SwapToDepositService(bags_client=fake)
        result = await svc.build_chain(
            input_mint=OUTPUT_MINT_STR,
            output_mint=OUTPUT_MINT_STR,
            amount_in=1,
            slippage_bps=50,
            depositor_pubkey=DEPOSITOR_STR,
            commitment_hex=COMMITMENT_HEX,
        )
        assert result["swap_tx"] == swap_b64


@pytest.mark.asyncio
async def test_build_chain_rejects_empty_swap_response() -> None:
    fake = _FakeBagsClient({"unrelated": "value"})
    svc = SwapToDepositService(bags_client=fake)
    with pytest.raises(ServiceUnavailableError):
        await svc.build_chain(
            input_mint=OUTPUT_MINT_STR,
            output_mint=OUTPUT_MINT_STR,
            amount_in=1,
            slippage_bps=50,
            depositor_pubkey=DEPOSITOR_STR,
            commitment_hex=COMMITMENT_HEX,
        )


@pytest.mark.asyncio
async def test_build_chain_requires_program_id() -> None:
    """The orchestrator MUST 503 when BAGSVAULT_PROGRAM_ID is empty."""

    settings.bagsvault_program_id = ""
    fake = _FakeBagsClient({"transaction": "ZHVtbXk="})
    svc = SwapToDepositService(bags_client=fake)
    with pytest.raises(ServiceUnavailableError):
        await svc.build_chain(
            input_mint=OUTPUT_MINT_STR,
            output_mint=OUTPUT_MINT_STR,
            amount_in=1,
            slippage_bps=50,
            depositor_pubkey=DEPOSITOR_STR,
            commitment_hex=COMMITMENT_HEX,
        )
