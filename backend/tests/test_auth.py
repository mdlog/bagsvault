"""Tests for Solana wallet signature verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import base58
import pytest
from nacl.signing import SigningKey

from app.auth import build_auth_message, require_wallet, verify_signature
from app.exceptions import AuthError


def _make_wallet() -> tuple[SigningKey, str]:
    sk = SigningKey.generate()
    pubkey_b58 = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    return sk, pubkey_b58


def _fake_request(headers: dict[str, str]) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    return req


def test_verify_signature_success() -> None:
    sk, address = _make_wallet()
    message = "hello bagsvault"
    sig = sk.sign(message.encode("utf-8")).signature
    sig_b58 = base58.b58encode(sig).decode("ascii")
    assert verify_signature(address, message, sig_b58) is True


def test_verify_signature_wrong_message_returns_false() -> None:
    sk, address = _make_wallet()
    sig = sk.sign(b"original").signature
    sig_b58 = base58.b58encode(sig).decode("ascii")
    assert verify_signature(address, "tampered", sig_b58) is False


def test_verify_signature_garbage_inputs_returns_false() -> None:
    assert verify_signature("not-base58!@#", "msg", "x") is False
    assert verify_signature("11111111111111111111111111111111", "msg", "ZZZ") is False


def test_build_auth_message_requires_tz() -> None:
    with pytest.raises(ValueError):
        build_auth_message(
            "bagsvault.app",
            "addr",
            "nonce",
            datetime(2024, 1, 1),  # naive
        )


def test_require_wallet_happy_path() -> None:
    sk, address = _make_wallet()
    issued_at = datetime.now(timezone.utc)
    message = build_auth_message("bagsvault.app", address, "nonce-123", issued_at)
    sig_b58 = base58.b58encode(sk.sign(message.encode("utf-8")).signature).decode("ascii")
    request = _fake_request(
        {
            "X-Wallet-Address": address,
            "X-Wallet-Signature": sig_b58,
            "X-Wallet-Message": message,
        }
    )
    assert require_wallet(request) == address


def test_require_wallet_missing_headers() -> None:
    request = _fake_request({})
    with pytest.raises(AuthError):
        require_wallet(request)


def test_require_wallet_replay_old_message() -> None:
    sk, address = _make_wallet()
    issued_at = datetime.now(timezone.utc) - timedelta(hours=2)
    message = build_auth_message("bagsvault.app", address, "nonce", issued_at)
    sig_b58 = base58.b58encode(sk.sign(message.encode("utf-8")).signature).decode("ascii")
    request = _fake_request(
        {
            "X-Wallet-Address": address,
            "X-Wallet-Signature": sig_b58,
            "X-Wallet-Message": message,
        }
    )
    with pytest.raises(AuthError) as ei:
        require_wallet(request)
    assert "expired" in str(ei.value).lower()


def test_require_wallet_address_mismatch() -> None:
    sk, address = _make_wallet()
    _, other_address = _make_wallet()
    issued_at = datetime.now(timezone.utc)
    message = build_auth_message("bagsvault.app", address, "nonce", issued_at)
    sig_b58 = base58.b58encode(sk.sign(message.encode("utf-8")).signature).decode("ascii")
    request = _fake_request(
        {
            "X-Wallet-Address": other_address,
            "X-Wallet-Signature": sig_b58,
            "X-Wallet-Message": message,
        }
    )
    with pytest.raises(AuthError):
        require_wallet(request)


def test_require_wallet_bad_signature() -> None:
    sk, address = _make_wallet()
    issued_at = datetime.now(timezone.utc)
    message = build_auth_message("bagsvault.app", address, "nonce", issued_at)
    # Sign a different message — signature won't verify against `message`.
    bad_sig = sk.sign(b"different").signature
    sig_b58 = base58.b58encode(bad_sig).decode("ascii")
    request = _fake_request(
        {
            "X-Wallet-Address": address,
            "X-Wallet-Signature": sig_b58,
            "X-Wallet-Message": message,
        }
    )
    with pytest.raises(AuthError):
        require_wallet(request)
