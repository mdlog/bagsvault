"""Tests for :mod:`app.clients.tx_executor`.

These tests use a hand-rolled fake :class:`SolanaRpc` rather than respx
because the executor's behaviour is determined entirely by the *shape*
of RPC responses — staying at the Protocol layer keeps the assertions
focused on retry/confirm/simulate logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.clients.solana_signer import SolanaSignerClient
from app.clients.tx_executor import TxExecutor, _classify_rpc_error
from app.exceptions import UpstreamError


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------
@dataclass
class _ExecSettings:
    """Mirror of the slice of ``app.config.Settings`` the executor reads."""

    tx_simulation_required: bool = True
    tx_priority_fee_microlamports: int = 1000
    tx_retry_max_attempts: int = 3
    tx_retry_initial_backoff_ms: int = 0  # zero so tests don't sleep
    tx_confirm_timeout_seconds: int = 5
    solana_commitment: str = "confirmed"
    relayer_max_compute_units: int = 400_000


@dataclass
class _FakeRpc:
    """Configurable Solana RPC stub for executor tests."""

    # Three distinct, valid 32-byte base58 hashes for retry tests.
    blockhashes: list[str] = field(
        default_factory=lambda: [
            "11111111111111111111111111111111",
            "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi",
            "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
        ]
    )
    simulate_results: list[dict[str, Any]] = field(
        default_factory=lambda: [{"err": None, "logs": ["Program log: ok"]}]
    )
    send_outcomes: list[Any] = field(default_factory=list)
    status_sequences: list[list[dict[str, Any] | None]] = field(default_factory=list)

    blockhash_calls: int = 0
    simulate_calls: int = 0
    send_calls: int = 0
    status_calls: int = 0

    sent_payloads: list[str] = field(default_factory=list)

    async def get_recent_blockhash(self) -> dict[str, Any]:
        idx = min(self.blockhash_calls, len(self.blockhashes) - 1)
        self.blockhash_calls += 1
        return {"blockhash": self.blockhashes[idx], "lastValidBlockHeight": 100 + idx}

    async def simulate_transaction(
        self, signed_tx_b64: str, replace_recent_blockhash: bool = False
    ) -> dict[str, Any]:
        idx = min(self.simulate_calls, len(self.simulate_results) - 1)
        self.simulate_calls += 1
        return self.simulate_results[idx]

    async def send_transaction(
        self, signed_tx_b64: str, skip_preflight: bool = False
    ) -> str:
        idx = min(self.send_calls, len(self.send_outcomes) - 1)
        outcome = self.send_outcomes[idx] if self.send_outcomes else "sigDefault"
        self.send_calls += 1
        self.sent_payloads.append(signed_tx_b64)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return str(outcome())
        return str(outcome)

    async def get_signature_statuses(
        self, signatures: list[str], search_transaction_history: bool = False
    ) -> list[dict[str, Any] | None]:
        if not self.status_sequences:
            self.status_calls += 1
            return [
                {"slot": 1, "confirmations": 1, "confirmationStatus": "confirmed", "err": None}
            ]
        idx = min(self.status_calls, len(self.status_sequences) - 1)
        self.status_calls += 1
        return self.status_sequences[idx]


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def signer(tmp_path: Path) -> SolanaSignerClient:
    kp = Keypair()
    path = tmp_path / "relayer.json"
    path.write_text(json.dumps(list(bytes(kp))))
    return SolanaSignerClient(keypair_path=path)


def _ix(payer: Pubkey) -> Instruction:
    return Instruction(
        program_id=Pubkey.default(),
        accounts=[AccountMeta(pubkey=payer, is_signer=True, is_writable=True)],
        data=b"\x00",
    )


# ----------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------
def test_classify_blockhash_not_found_is_retryable() -> None:
    assert _classify_rpc_error("BlockhashNotFound") == "retryable"


def test_classify_node_is_behind_is_retryable() -> None:
    assert _classify_rpc_error({"message": "Node is behind by 12 slots"}) == "retryable"


def test_classify_429_is_retryable() -> None:
    assert _classify_rpc_error("HTTP 429 too many requests") == "retryable"


@pytest.mark.parametrize("status", ["502", "503", "504"])
def test_classify_5xx_is_retryable(status: str) -> None:
    assert _classify_rpc_error(f"HTTP {status} bad gateway") == "retryable"


def test_classify_insufficient_funds_is_fatal() -> None:
    assert _classify_rpc_error("InsufficientFundsForRent") == "fatal"


def test_classify_invalid_account_data_is_fatal() -> None:
    assert _classify_rpc_error("InvalidAccountData") == "fatal"


def test_classify_account_not_found_is_fatal() -> None:
    assert _classify_rpc_error("AccountNotFound") == "fatal"


def test_classify_unknown_defaults_to_fatal() -> None:
    assert _classify_rpc_error("totally novel error string") == "fatal"


# ----------------------------------------------------------------------
# send() — happy path
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_happy_path_returns_tx_result(signer: SolanaSignerClient) -> None:
    rpc = _FakeRpc(
        send_outcomes=["sigOK"],
        status_sequences=[
            [{"slot": 42, "confirmationStatus": "confirmed", "err": None}],
        ],
    )
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=_ExecSettings())
    payer = signer.pubkey_obj()

    result = await executor.send([_ix(payer)], payer=payer)

    assert result.signature == "sigOK"
    assert result.status == "confirmed"
    assert result.attempts == 1
    assert result.slot == 42
    # Compute-budget instructions were prepended, so the broadcast
    # payload differs from a bare ix-only build.
    assert rpc.simulate_calls == 1
    assert rpc.send_calls == 1


# ----------------------------------------------------------------------
# Simulation failure must be fatal
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_aborts_when_simulation_returns_err(
    signer: SolanaSignerClient,
) -> None:
    rpc = _FakeRpc(
        simulate_results=[
            {"err": {"InstructionError": [0, "Custom"]}, "logs": ["Program log: nope"]}
        ],
    )
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=_ExecSettings())
    payer = signer.pubkey_obj()

    with pytest.raises(UpstreamError) as ei:
        await executor.send([_ix(payer)], payer=payer)

    assert "tx simulation failed" in ei.value.message
    assert ei.value.details["stage"] == "simulate"
    # The cluster has rejected — we must not have broadcast.
    assert rpc.send_calls == 0


# ----------------------------------------------------------------------
# Retry on blockhash expired
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_retries_on_blockhash_expired_then_succeeds(
    signer: SolanaSignerClient,
) -> None:
    rpc = _FakeRpc(
        send_outcomes=[
            Exception("RPC error: BlockhashNotFound"),
            "sigRetry",
        ],
        status_sequences=[
            [{"slot": 7, "confirmationStatus": "confirmed", "err": None}],
        ],
    )
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=_ExecSettings())
    payer = signer.pubkey_obj()

    result = await executor.send([_ix(payer)], payer=payer)

    assert result.signature == "sigRetry"
    assert result.attempts == 2
    # Blockhash refreshed for the retry: we fetched once initially and
    # once again before resigning.
    assert rpc.blockhash_calls == 2
    # And the retry payload differs from the first attempt because the
    # blockhash baked into the message changed.
    assert rpc.sent_payloads[0] != rpc.sent_payloads[1]


# ----------------------------------------------------------------------
# Retry on rate limit
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_retries_on_rate_limit_then_succeeds(
    signer: SolanaSignerClient,
) -> None:
    rpc = _FakeRpc(
        send_outcomes=[
            Exception("HTTP 429: too many requests"),
            "sigOk",
        ],
        status_sequences=[
            [{"slot": 1, "confirmationStatus": "finalized", "err": None}],
        ],
    )
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=_ExecSettings())
    payer = signer.pubkey_obj()

    result = await executor.send([_ix(payer)], payer=payer)
    assert result.signature == "sigOk"
    assert result.attempts == 2


# ----------------------------------------------------------------------
# Fatal error is not retried
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_does_not_retry_fatal_error(signer: SolanaSignerClient) -> None:
    rpc = _FakeRpc(
        send_outcomes=[Exception("InsufficientFundsForRent")],
    )
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=_ExecSettings())
    payer = signer.pubkey_obj()

    with pytest.raises(Exception) as ei:
        await executor.send([_ix(payer)], payer=payer)

    assert "InsufficientFundsForRent" in str(ei.value)
    assert rpc.send_calls == 1


# ----------------------------------------------------------------------
# Confirm timeout
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_raises_on_confirm_timeout(
    signer: SolanaSignerClient,
) -> None:
    # Status sequence keeps returning ``None`` (signature unknown), so
    # the polling loop will exhaust the deadline.
    rpc = _FakeRpc(
        send_outcomes=["sigPending"],
        status_sequences=[[None] * 100],
    )
    settings = _ExecSettings(tx_confirm_timeout_seconds=1)
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=settings)
    payer = signer.pubkey_obj()

    with pytest.raises(UpstreamError) as ei:
        await executor.send([_ix(payer)], payer=payer)

    assert "tx confirm timeout" in ei.value.message
    assert ei.value.details["stage"] == "confirm"
    assert "elapsed_seconds" in ei.value.details
    assert ei.value.details["target_commitment"] == "confirmed"


# ----------------------------------------------------------------------
# Compute budget injection
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_skips_priority_fee_ix_when_zero(
    signer: SolanaSignerClient,
) -> None:
    rpc_with_fee = _FakeRpc(
        send_outcomes=["sigA"],
        status_sequences=[
            [{"slot": 1, "confirmationStatus": "confirmed", "err": None}],
        ],
    )
    rpc_no_fee = _FakeRpc(
        send_outcomes=["sigB"],
        status_sequences=[
            [{"slot": 1, "confirmationStatus": "confirmed", "err": None}],
        ],
    )
    payer = signer.pubkey_obj()

    exec_with = TxExecutor(
        rpc=rpc_with_fee,
        signer=signer,
        settings_obj=_ExecSettings(tx_priority_fee_microlamports=5000),
    )
    exec_without = TxExecutor(
        rpc=rpc_no_fee,
        signer=signer,
        settings_obj=_ExecSettings(tx_priority_fee_microlamports=0),
    )

    await exec_with.send([_ix(payer)], payer=payer)
    await exec_without.send([_ix(payer)], payer=payer)

    # The ``set_compute_unit_price`` ix must lengthen the payload — we
    # simply confirm the byte payloads differ between the two configs.
    assert rpc_with_fee.sent_payloads[0] != rpc_no_fee.sent_payloads[0]


# ----------------------------------------------------------------------
# Simulation can be disabled
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_skips_simulation_when_disabled(
    signer: SolanaSignerClient,
) -> None:
    rpc = _FakeRpc(
        send_outcomes=["sigSkip"],
        status_sequences=[
            [{"slot": 1, "confirmationStatus": "confirmed", "err": None}],
        ],
    )
    settings = _ExecSettings(tx_simulation_required=False)
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=settings)
    payer = signer.pubkey_obj()
    result = await executor.send([_ix(payer)], payer=payer)
    assert result.signature == "sigSkip"
    assert rpc.simulate_calls == 0


# ----------------------------------------------------------------------
# Retry budget exhaustion
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_raises_when_retries_exhausted(
    signer: SolanaSignerClient,
) -> None:
    rpc = _FakeRpc(
        send_outcomes=[
            Exception("BlockhashNotFound"),
            Exception("BlockhashNotFound"),
            Exception("BlockhashNotFound"),
        ],
    )
    settings = _ExecSettings(tx_retry_max_attempts=3)
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=settings)
    payer = signer.pubkey_obj()

    with pytest.raises(UpstreamError) as ei:
        await executor.send([_ix(payer)], payer=payer)

    assert "exhausted retries" in ei.value.message
    assert ei.value.details["attempts"] == 3
    assert rpc.send_calls == 3


# ----------------------------------------------------------------------
# Confirm propagates on-chain error
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_raises_when_confirm_reports_err(
    signer: SolanaSignerClient,
) -> None:
    rpc = _FakeRpc(
        send_outcomes=["sigErr"],
        status_sequences=[
            [
                {
                    "slot": 5,
                    "confirmationStatus": "confirmed",
                    "err": {"InstructionError": [0, "Custom"]},
                }
            ]
        ],
    )
    executor = TxExecutor(rpc=rpc, signer=signer, settings_obj=_ExecSettings())
    payer = signer.pubkey_obj()

    with pytest.raises(UpstreamError) as ei:
        await executor.send([_ix(payer)], payer=payer)

    assert ei.value.details["stage"] == "confirm"
    assert "err" in ei.value.details
