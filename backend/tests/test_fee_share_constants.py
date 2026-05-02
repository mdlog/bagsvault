"""Regression guard for the Fee Share V2 program-ID constant.

The address ``FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK`` is sourced
from Bags' published program-IDs page (``docs.bags.fm/principles/program-ids``)
and pinned in two places:

  * ``programs/bagsvault/src/fee_share.rs::FEE_SHARE_V2_PROGRAM_ID``
  * ``backend/app/config.py::Settings.bagsvault_fee_share_program_id``

This test asserts the backend constant byte-for-byte. The Rust constant
is regression-checked at compile time by the ``pubkey!`` macro, so a
typo there would fail the build.
"""

from __future__ import annotations

from solders.pubkey import Pubkey

from app.config import settings


EXPECTED_FEE_SHARE_V2_PROGRAM_ID = "FEE2tBhCKAt7shrod19QttSVREUYPiyMzoku1mL1gqVK"


def test_fee_share_program_id_default() -> None:
    """Default ``BAGSVAULT_FEE_SHARE_PROGRAM_ID`` must match Bags' docs."""

    assert settings.bagsvault_fee_share_program_id == EXPECTED_FEE_SHARE_V2_PROGRAM_ID


def test_fee_share_program_id_is_valid_base58_pubkey() -> None:
    """Constant decodes to a 32-byte Solana pubkey."""

    pk = Pubkey.from_string(settings.bagsvault_fee_share_program_id)
    assert len(bytes(pk)) == 32
    assert str(pk) == EXPECTED_FEE_SHARE_V2_PROGRAM_ID
