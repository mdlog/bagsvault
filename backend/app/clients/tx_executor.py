"""Transaction executor: simulate -> broadcast -> confirm with retry.

The :class:`TxExecutor` is the only place the BagsVault backend builds,
signs, simulates, broadcasts, and confirms a Solana transaction. It
encapsulates the production hardening required for Phase 3:

* Inject compute-budget instructions (priority fee + compute unit limit)
  so transactions land predictably during congestion.
* Optionally simulate before broadcast — a failed simulation is treated
  as a fatal error and short-circuits the retry loop (no point burning
  attempts on a tx the cluster has already rejected).
* Classify RPC errors as either *retryable* (blockhash expired, rate
  limit, transient 5xx) or *fatal* (insufficient funds, invalid account,
  simulation error) and only retry the former, refreshing the blockhash
  + rebuilding the transaction between attempts with exponential backoff.
* Poll ``getSignatureStatuses`` until the tx reaches the configured
  commitment level or the timeout elapses.

The executor accepts a settings object for testability — pass the
project ``settings`` singleton in production, or a stand-in ``Settings``
in tests so retry counts/backoffs can be made deterministic.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from app.clients.solana_signer import SolanaSignerClient
from app.exceptions import UpstreamError

logger = logging.getLogger(__name__)


# Commitment ranks used to decide whether a poll result satisfies the
# operator-configured target commitment ("processed" < "confirmed" <
# "finalized"). A status that meets *or exceeds* the target is treated
# as confirmation.
_COMMITMENT_RANK: dict[str, int] = {
    "processed": 0,
    "confirmed": 1,
    "finalized": 2,
}


# Substrings used to detect retryable upstream conditions in a
# best-effort, lower-cased match. The Solana RPC layer surfaces the
# same condition under several phrasings depending on cluster / RPC
# vendor — we accept all of them.
_RETRYABLE_MARKERS: tuple[str, ...] = (
    # Blockhash already expired — refresh and retry. (RPC error message.)
    "blockhashnotfound",
    "block not available",
    # Node still catching up to the leader. Retry with backoff.
    "node is behind",
    # Rate limit / overload from the upstream RPC vendor.
    "429",
    "rate limit",
    "too many requests",
    # Transient 5xx flavours — the request never reached consensus.
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)

# Substrings that mean the cluster has firmly rejected the tx — never retry.
_FATAL_MARKERS: tuple[str, ...] = (
    # Account-state errors are deterministic — retrying with a new
    # blockhash will produce the same failure.
    "insufficientfundsforrent",
    "insufficient funds",
    "invalidaccountdata",
    "accountnotfound",
    "instructionerror",
    "transaction simulation failed",
)


class SolanaRpc(Protocol):
    """Subset of :class:`app.clients.solana_rpc.SolanaRpcClient` we depend on."""

    async def get_recent_blockhash(self) -> Any: ...

    async def send_transaction(
        self, signed_tx_b64: str, skip_preflight: bool = False
    ) -> str: ...

    async def simulate_transaction(
        self, signed_tx_b64: str, replace_recent_blockhash: bool = False
    ) -> dict[str, Any]: ...

    async def get_signature_statuses(
        self, signatures: list[str], search_transaction_history: bool = False
    ) -> list[dict[str, Any] | None]: ...


class _ExecutorSettings(Protocol):
    """The slice of ``app.config.Settings`` ``TxExecutor`` reads."""

    tx_simulation_required: bool
    tx_priority_fee_microlamports: int
    tx_retry_max_attempts: int
    tx_retry_initial_backoff_ms: int
    tx_confirm_timeout_seconds: int
    solana_commitment: str
    relayer_max_compute_units: int


class TxResult(BaseModel):
    """Outcome of a successful :meth:`TxExecutor.send` call."""

    signature: str
    status: str
    attempts: int
    slot: int | None = None
    simulation_logs: list[str] = []


def _coerce_blockhash(raw: Any) -> str:
    """Accept either a raw blockhash string or the ``getLatestBlockhash`` dict."""

    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        value = raw.get("blockhash")
        if isinstance(value, str):
            return value
    raise UpstreamError(
        "Solana RPC returned an unexpected blockhash payload.",
        details={"type": type(raw).__name__},
    )


def _classify_rpc_error(err: Any) -> Literal["retryable", "fatal"]:
    """Classify an upstream RPC error as retryable or fatal.

    Rules (each corresponds to a real Solana RPC error message):

    * ``BlockhashNotFound`` / ``Block not available`` -> retryable
      (the blockhash slot has rolled past — fetch a new one).
    * ``Node is behind`` -> retryable (RPC lagging the leader).
    * HTTP 429 / "rate limit" / "too many requests" -> retryable
      (vendor throttle).
    * HTTP 502 / 503 / 504 / "bad gateway" / "service unavailable" /
      "gateway timeout" -> retryable (transient infra failure).
    * ``InsufficientFundsForRent`` / ``insufficient funds`` -> fatal
      (relayer wallet is empty — operator must top it up).
    * ``InvalidAccountData`` / ``AccountNotFound`` -> fatal
      (deterministic ix-layout or PDA derivation mistake).
    * ``InstructionError`` / ``Transaction simulation failed`` -> fatal
      (program rejected the call; retrying makes no difference).
    * Anything not matched -> fatal by default — better to surface an
      unknown error than to burn retries on a deterministic failure.
    """

    text = ""
    if isinstance(err, dict):
        # Walk a couple of standard locations — Solana RPC uses
        # ``{"err": {...}}`` for simulation results and
        # ``{"message": "..."}`` for the JSON-RPC envelope.
        for key in ("message", "Err", "err"):
            value = err.get(key)
            if value is not None:
                text += f" {value}"
        text += f" {err}"
    else:
        text = str(err)

    lowered = text.lower()
    for marker in _FATAL_MARKERS:
        if marker in lowered:
            return "fatal"
    for marker in _RETRYABLE_MARKERS:
        if marker in lowered:
            return "retryable"
    return "fatal"


def _meets_commitment(
    status: dict[str, Any] | None, target: str
) -> bool:
    """Return True if ``status`` is at or above the target commitment."""

    if status is None:
        return False
    actual = status.get("confirmationStatus")
    if not isinstance(actual, str):
        return False
    target_rank = _COMMITMENT_RANK.get(target, 1)
    actual_rank = _COMMITMENT_RANK.get(actual, -1)
    return actual_rank >= target_rank


class TxExecutor:
    """Build, simulate, broadcast, and confirm a Solana transaction with retry."""

    def __init__(
        self,
        rpc: SolanaRpc,
        signer: SolanaSignerClient,
        settings_obj: _ExecutorSettings,
    ) -> None:
        self._rpc = rpc
        self._signer = signer
        self._settings = settings_obj

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send(
        self,
        instructions: list[Instruction],
        payer: Pubkey,
        *,
        recent_blockhash: str | None = None,
        additional_signers: list[Keypair] | None = None,
    ) -> TxResult:
        """Build, simulate (if required), broadcast, and confirm a transaction.

        The pipeline:

        1. Prepend compute-budget instructions (priority fee + unit limit)
           using the settings-derived configuration.
        2. Fetch a recent blockhash unless one was supplied.
        3. Compile a v0 message and sign with the relayer keypair plus any
           ``additional_signers``.
        4. If ``tx_simulation_required`` is on, simulate first. A
           non-null ``err`` aborts immediately with no retries.
        5. Broadcast. On retryable errors refresh the blockhash, rebuild,
           and retry up to ``tx_retry_max_attempts`` with exponential
           backoff. On fatal errors abort.
        6. Poll ``getSignatureStatuses`` until the configured commitment
           is reached or ``tx_confirm_timeout_seconds`` elapses.
        """

        full_instructions = self._with_compute_budget(instructions)
        blockhash = recent_blockhash or _coerce_blockhash(
            await self._rpc.get_recent_blockhash()
        )

        signed_b64 = self._build_signed_b64(
            full_instructions, payer, blockhash, additional_signers
        )

        simulation_logs: list[str] = []
        if self._settings.tx_simulation_required:
            sim_result = await self._rpc.simulate_transaction(signed_b64)
            sim_err = sim_result.get("err")
            sim_logs_raw = sim_result.get("logs") or []
            if isinstance(sim_logs_raw, list):
                simulation_logs = [str(line) for line in sim_logs_raw]
            if sim_err is not None:
                logger.warning(
                    "tx simulation failed err=%s logs=%s",
                    sim_err,
                    simulation_logs[-5:],
                )
                raise UpstreamError(
                    "tx simulation failed",
                    details={
                        "stage": "simulate",
                        "err": sim_err,
                        "logs": simulation_logs,
                    },
                )

        signature = await self._broadcast_with_retry(
            full_instructions, payer, blockhash, signed_b64, additional_signers
        )

        slot = await self._await_confirmation(signature)
        attempts_used = self._last_attempts_used
        return TxResult(
            signature=signature,
            status="confirmed",
            attempts=attempts_used,
            slot=slot,
            simulation_logs=simulation_logs,
        )

    # ------------------------------------------------------------------
    # Internal: tx building
    # ------------------------------------------------------------------
    def _with_compute_budget(
        self, instructions: list[Instruction]
    ) -> list[Instruction]:
        """Prepend compute-budget instructions if priced > 0 / units > 0."""

        prelude: list[Instruction] = []
        max_units = int(self._settings.relayer_max_compute_units)
        if max_units > 0:
            prelude.append(set_compute_unit_limit(max_units))
        priority_fee = int(self._settings.tx_priority_fee_microlamports)
        if priority_fee > 0:
            prelude.append(set_compute_unit_price(priority_fee))
        return [*prelude, *instructions]

    def _build_signed_b64(
        self,
        instructions: list[Instruction],
        payer: Pubkey,
        recent_blockhash: str,
        additional_signers: list[Keypair] | None,
    ) -> str:
        """Compile + sign a v0 transaction and return its base64 body.

        Delegates the relayer signature to ``SolanaSignerClient.build_and_sign``
        so the executor never sees the relayer secret. When the message
        requires extra signers (e.g. an ephemeral nonce keypair) the
        caller passes them via ``additional_signers``; we re-sign the
        compiled tx with the additional set on top of the relayer's
        signature by reconstructing a :class:`VersionedTransaction` from
        the compiled message.
        """

        try:
            relayer_signed_bytes = self._signer.build_and_sign(
                instructions=instructions,
                recent_blockhash=recent_blockhash,
                payer=payer,
            )
        except UpstreamError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(
                "Failed to build and sign transaction.",
                details={"error": str(exc)},
            ) from exc

        if additional_signers:
            # Pull the message back out and re-sign with the full set so
            # the additional signers' signatures are attached. solders
            # sorts signatures by message header position.
            relayer_tx = VersionedTransaction.from_bytes(relayer_signed_bytes)
            full = VersionedTransaction(relayer_tx.message, list(additional_signers))
            relayer_signed_bytes = bytes(full)

        return base64.b64encode(relayer_signed_bytes).decode("ascii")

    # ------------------------------------------------------------------
    # Internal: broadcast loop with retry
    # ------------------------------------------------------------------
    async def _broadcast_with_retry(
        self,
        instructions: list[Instruction],
        payer: Pubkey,
        blockhash: str,
        signed_b64: str,
        additional_signers: list[Keypair] | None,
    ) -> str:
        max_attempts = max(1, int(self._settings.tx_retry_max_attempts))
        backoff_base_ms = max(0, int(self._settings.tx_retry_initial_backoff_ms))

        last_exc: Exception | None = None
        current_blockhash = blockhash
        current_payload = signed_b64

        for attempt in range(max_attempts):
            try:
                # Preflight already done in the simulate step (when enabled);
                # skip it here to halve the RPC round-trip count.
                signature = await self._rpc.send_transaction(
                    current_payload, skip_preflight=True
                )
                self._last_attempts_used = attempt + 1
                return signature
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                classification = _classify_rpc_error(exc)
                logger.warning(
                    "tx broadcast attempt=%d/%d classification=%s err=%s",
                    attempt + 1,
                    max_attempts,
                    classification,
                    exc,
                )
                if classification == "fatal":
                    raise
                if attempt + 1 >= max_attempts:
                    break
                # Refresh blockhash + rebuild before the next attempt.
                try:
                    current_blockhash = _coerce_blockhash(
                        await self._rpc.get_recent_blockhash()
                    )
                    current_payload = self._build_signed_b64(
                        instructions, payer, current_blockhash, additional_signers
                    )
                except Exception as inner_exc:  # noqa: BLE001
                    last_exc = inner_exc
                backoff_ms = backoff_base_ms * (2**attempt)
                await asyncio.sleep(backoff_ms / 1000)

        raise UpstreamError(
            "tx broadcast exhausted retries",
            details={
                "stage": "broadcast",
                "attempts": max_attempts,
                "last_error": str(last_exc) if last_exc is not None else None,
            },
        )

    # ------------------------------------------------------------------
    # Internal: confirmation polling
    # ------------------------------------------------------------------
    async def _await_confirmation(self, signature: str) -> int | None:
        target = self._settings.solana_commitment
        timeout = max(1, int(self._settings.tx_confirm_timeout_seconds))
        deadline = time.monotonic() + timeout

        # Poll roughly every 500ms — Solana slots are ~400ms so this is a
        # reasonable cadence without hammering the RPC.
        poll_interval_s = 0.5
        while True:
            statuses = await self._rpc.get_signature_statuses([signature])
            status = statuses[0] if statuses else None
            if status is not None:
                err = status.get("err")
                if err is not None:
                    raise UpstreamError(
                        "tx confirmation reported on-chain error",
                        details={
                            "stage": "confirm",
                            "signature": signature,
                            "err": err,
                        },
                    )
                if _meets_commitment(status, target):
                    slot = status.get("slot")
                    return slot if isinstance(slot, int) else None
            elapsed = time.monotonic() - (deadline - timeout)
            if time.monotonic() >= deadline:
                raise UpstreamError(
                    "tx confirm timeout",
                    details={
                        "stage": "confirm",
                        "signature": signature,
                        "elapsed_seconds": round(elapsed, 2),
                        "target_commitment": target,
                    },
                )
            await asyncio.sleep(poll_interval_s)

    # Tracks how many broadcast attempts the most recent ``send`` call
    # consumed; populated from inside ``_broadcast_with_retry``.
    _last_attempts_used: int = 0
