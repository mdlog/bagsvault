"""Solana keypair loader + transaction signer for the relayer node.

The relayer is the entity that pays SOL gas on behalf of withdrawal users
so they can receive funds at a fresh wallet without ever holding gas. This
module isolates the only code path that touches the relayer secret key:

* lazy load the keypair from the operator-supplied JSON file (Solana CLI
  format — a list of 64 ints holding the full 64-byte secret),
* expose its base58 ``pubkey()`` for advertising in
  ``/api/relayers``,
* sign already-built ``VersionedTransaction``s,
* and offer a one-shot ``build_and_sign()`` convenience that wraps the
  ``MessageV0`` compile step.

If the keypair file is missing, malformed, or the wrong length we raise
:class:`ServiceUnavailableError` so the FastAPI handler returns a clean
HTTP 503 with operator-facing details instead of a stack trace.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Union

from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from app.config import settings
from app.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


SignableTransaction = Union[VersionedTransaction, bytes]


class SolanaSignerClient:
    """Lazy keypair loader + signer for the relayer wallet.

    The instance is safe to share across the process — :class:`Keypair`
    from solders is immutable once constructed and signing is a pure
    function of its bytes.
    """

    def __init__(self, *, keypair_path: Path | None = None) -> None:
        # Resolve lazily: tests can construct this client before .env exists.
        self._configured_path = keypair_path
        self._keypair: Keypair | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _resolve_path(self) -> Path:
        if self._configured_path is not None:
            return self._configured_path
        return settings.keypair_path(settings.solana_relayer_keypair)

    def _load(self) -> Keypair:
        if self._keypair is not None:
            return self._keypair

        path = self._resolve_path()
        if not path.exists():
            raise ServiceUnavailableError(
                "Relayer keypair not configured.",
                details={"missing_path": str(path)},
            )

        try:
            raw = path.read_text()
            secret = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ServiceUnavailableError(
                "Relayer keypair not configured.",
                details={"path": str(path), "error": str(exc)},
            ) from exc

        if not isinstance(secret, list) or not all(isinstance(b, int) for b in secret):
            raise ServiceUnavailableError(
                "Relayer keypair not configured.",
                details={"path": str(path), "error": "expected JSON array of ints"},
            )

        try:
            keypair = Keypair.from_bytes(bytes(secret))
        except Exception as exc:  # noqa: BLE001 — surface as 503
            raise ServiceUnavailableError(
                "Relayer keypair not configured.",
                details={"path": str(path), "error": str(exc)},
            ) from exc

        self._keypair = keypair
        logger.info("relayer keypair loaded path=%s pubkey=%s", path, keypair.pubkey())
        return keypair

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def pubkey(self) -> str:
        """Return the relayer wallet's public key as a base58 string."""

        return str(self._load().pubkey())

    def pubkey_obj(self) -> Pubkey:
        """Return the relayer wallet's public key as a solders ``Pubkey``."""

        return self._load().pubkey()

    def sign_transaction(self, unsigned_tx: SignableTransaction) -> bytes:
        """Sign ``unsigned_tx`` with the relayer keypair.

        Accepts either a :class:`VersionedTransaction` (already compiled
        with this signer as a required signer) or raw transaction bytes
        produced by the Solana RPC builder. Returns the serialized signed
        transaction as raw bytes — encode with base64 before sending over
        JSON-RPC.
        """

        keypair = self._load()
        if isinstance(unsigned_tx, (bytes, bytearray)):
            tx = VersionedTransaction.from_bytes(bytes(unsigned_tx))
        else:
            tx = unsigned_tx

        # Reconstruct with the relayer signature attached. solders'
        # VersionedTransaction is immutable; the documented way to sign
        # is to re-build from message + signers.
        signed = VersionedTransaction(tx.message, [keypair])
        return bytes(signed)

    def build_and_sign(
        self,
        instructions: list[Instruction],
        recent_blockhash: str,
        payer: Pubkey | None = None,
    ) -> bytes:
        """Compile a v0 transaction from ``instructions`` and sign it.

        ``recent_blockhash`` is the base58 hash returned by
        ``getLatestBlockhash``. ``payer`` defaults to the relayer pubkey.
        Returns the serialized signed transaction (caller base64-encodes
        for the JSON-RPC envelope).
        """

        keypair = self._load()
        payer_pubkey = payer if payer is not None else keypair.pubkey()
        try:
            blockhash = Hash.from_string(recent_blockhash)
        except Exception as exc:  # noqa: BLE001
            raise ServiceUnavailableError(
                "Invalid recent blockhash supplied to signer.",
                details={"blockhash": recent_blockhash, "error": str(exc)},
            ) from exc

        message = MessageV0.try_compile(
            payer=payer_pubkey,
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )
        tx = VersionedTransaction(message, [keypair])
        return bytes(tx)


# ----------------------------------------------------------------------
# Module-level singleton + factory
# ----------------------------------------------------------------------
_signer_client: SolanaSignerClient | None = None


def get_solana_signer_client() -> SolanaSignerClient:
    """Return the process-level :class:`SolanaSignerClient` singleton."""

    global _signer_client
    if _signer_client is None:
        _signer_client = SolanaSignerClient()
    return _signer_client


def reset_solana_signer_client() -> None:
    """Test helper: clear the cached singleton so a new keypair path is picked up."""

    global _signer_client
    _signer_client = None
