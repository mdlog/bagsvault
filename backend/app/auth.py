"""Sign-in-with-Solana wallet authentication.

Implements a lightweight Ed25519 signature verification flow that lets
clients prove control of a Solana wallet without us holding a session
token. The frontend builds a canonical message via
:func:`build_auth_message`, asks the wallet to sign it, then sends:

* ``X-Wallet-Address``   — base58 Solana pubkey
* ``X-Wallet-Message``   — the exact message that was signed
* ``X-Wallet-Signature`` — base58 Ed25519 signature

The dependency :func:`require_wallet` verifies all three and raises
:class:`AuthError` on any mismatch or replay.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import base58
import nacl.exceptions
from fastapi import Request
from nacl.signing import VerifyKey

from app.config import settings
from app.exceptions import AuthError

logger = logging.getLogger(__name__)

_AUTH_MESSAGE_TEMPLATE = (
    "{domain} wants you to sign in with your Solana account:\n"
    "{address}\n\n"
    "Authorize BagsVault session.\n\n"
    "Nonce: {nonce}\n"
    "Issued At: {issued_at}"
)

# Issued-At line, e.g. "Issued At: 2024-05-02T10:23:00+00:00".
_ISSUED_AT_RE = re.compile(r"^Issued At:\s*(?P<ts>\S+)\s*$", re.MULTILINE)
# Address appears on the second line per the SIWE-style template above.
_ADDRESS_LINE_RE = re.compile(r"sign in with your Solana account:\n(?P<addr>[^\n]+)")


def build_auth_message(domain: str, address: str, nonce: str, issued_at: datetime) -> str:
    """Build the canonical sign-in message.

    The ``issued_at`` timestamp must be timezone-aware and is serialized to
    ISO-8601 with offset, matching what :func:`require_wallet` parses.
    """

    if issued_at.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware")
    return _AUTH_MESSAGE_TEMPLATE.format(
        domain=domain,
        address=address,
        nonce=nonce,
        issued_at=issued_at.isoformat(),
    )


def verify_signature(address: str, message: str, signature_b58: str) -> bool:
    """Verify ``signature_b58`` is a valid Ed25519 signature of ``message``
    by the wallet identified by base58-encoded ``address``.

    Returns ``True`` on success and ``False`` if the inputs are malformed or
    the signature doesn't verify. Never raises.
    """

    try:
        pubkey_bytes = base58.b58decode(address)
        signature_bytes = base58.b58decode(signature_b58)
    except (ValueError, TypeError):
        return False

    if len(pubkey_bytes) != 32 or len(signature_bytes) != 64:
        return False

    try:
        VerifyKey(pubkey_bytes).verify(message.encode("utf-8"), signature_bytes)
    except nacl.exceptions.BadSignatureError:
        return False
    except Exception:  # noqa: BLE001 — defensive; treat any nacl error as failure
        logger.exception("Unexpected error verifying wallet signature")
        return False
    return True


def _extract_issued_at(message: str) -> datetime:
    match = _ISSUED_AT_RE.search(message)
    if not match:
        raise AuthError("Auth message missing 'Issued At' field.")
    raw = match.group("ts")
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise AuthError("Auth message has malformed 'Issued At' timestamp.") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _extract_address(message: str) -> str | None:
    match = _ADDRESS_LINE_RE.search(message)
    if not match:
        return None
    return match.group("addr").strip()


def require_wallet(request: Request) -> str:
    """FastAPI dependency: verify wallet headers and return the pubkey.

    Raises :class:`AuthError` (HTTP 401) when:

    * Any of the three headers are missing.
    * The address embedded in the message doesn't match ``X-Wallet-Address``.
    * The signature doesn't verify against the message.
    * The message's ``Issued At`` is older than
      ``settings.auth_message_max_age_seconds`` (replay protection) or in
      the future by more than 60 seconds (clock skew tolerance).
    """

    address = request.headers.get("X-Wallet-Address")
    signature = request.headers.get("X-Wallet-Signature")
    message = request.headers.get("X-Wallet-Message")

    if not address or not signature or not message:
        raise AuthError(
            "Missing wallet auth headers.",
            details={"required": ["X-Wallet-Address", "X-Wallet-Signature", "X-Wallet-Message"]},
        )

    msg_address = _extract_address(message)
    if msg_address is not None and msg_address != address:
        raise AuthError("Auth message address does not match X-Wallet-Address header.")

    issued_at = _extract_issued_at(message)
    now = datetime.now(timezone.utc)
    age_seconds = (now - issued_at).total_seconds()
    if age_seconds > settings.auth_message_max_age_seconds:
        raise AuthError(
            "Auth message expired.",
            details={"age_seconds": age_seconds, "max_age": settings.auth_message_max_age_seconds},
        )
    if age_seconds < -60:
        raise AuthError(
            "Auth message issued in the future.",
            details={"age_seconds": age_seconds},
        )

    if not verify_signature(address, message, signature):
        raise AuthError("Invalid wallet signature.")

    return address
