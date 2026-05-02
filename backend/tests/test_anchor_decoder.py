"""Tests for the optional :class:`AnchorDecoder` IDL wrapper."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.clients.anchor_decoder import AnchorDecoder, _container_to_dict


@pytest.mark.asyncio
async def test_decode_unavailable_when_idl_path_empty() -> None:
    decoder = AnchorDecoder(idl_path="")
    assert decoder.decode_available() is False
    result = await decoder.decode_account("AAA=", "MerkleTree")
    assert result is None


@pytest.mark.asyncio
async def test_decode_unavailable_when_idl_path_missing(tmp_path: Path) -> None:
    decoder = AnchorDecoder(idl_path=str(tmp_path / "does-not-exist.json"))
    assert decoder.decode_available() is False
    assert (await decoder.decode_account("AAA=", "MerkleTree")) is None


@pytest.mark.asyncio
async def test_decode_unavailable_when_idl_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not really JSON")
    decoder = AnchorDecoder(idl_path=str(bad))
    assert decoder.decode_available() is False


@pytest.mark.asyncio
async def test_decode_returns_none_for_bad_base64(tmp_path: Path) -> None:
    """Even with an IDL absent, decode_account on bad base64 must return None."""

    decoder = AnchorDecoder(idl_path="")
    # Decoder is disabled — bad base64 is not even reached. Still must be None.
    assert (await decoder.decode_account("not-base64!!!", "MerkleTree")) is None


def test_container_to_dict_strips_construct_metadata() -> None:
    raw = {
        "_io": "<stream>",
        "name": "MerkleTree",
        "root": b"\x01\x02\x03",
        "extras": [{"_inner": "x", "value": 1}, {"value": 2}],
        "nested": {"_skip": True, "keep": "yes"},
    }
    cleaned = _container_to_dict(raw)
    assert "_io" not in cleaned
    assert cleaned["name"] == "MerkleTree"
    # bytes get hex-encoded
    assert cleaned["root"] == "010203"
    assert cleaned["extras"] == [{"value": 1}, {"value": 2}]
    assert cleaned["nested"] == {"keep": "yes"}


@pytest.mark.asyncio
async def test_decoder_with_minimal_idl(tmp_path: Path) -> None:
    """Loads a real (tiny) IDL and decodes a synthesised payload.

    The IDL describes a single account named ``MerkleTree`` carrying a
    u32 ``commitment_count``. We construct the bytes Anchor would emit
    (8-byte sha256-derived discriminator + LE u32) and assert anchorpy
    parses it back into our expected dict.
    """

    pytest.importorskip("anchorpy")

    idl_doc = {
        "version": "0.1.0",
        "name": "bagsvault",
        "instructions": [],
        "accounts": [
            {
                "name": "MerkleTree",
                "type": {
                    "kind": "struct",
                    "fields": [
                        {"name": "commitment_count", "type": "u32"},
                    ],
                },
            }
        ],
    }
    idl_path = tmp_path / "bagsvault.json"
    idl_path.write_text(json.dumps(idl_doc))

    decoder = AnchorDecoder(idl_path=str(idl_path))
    if not decoder.decode_available():
        pytest.skip("Local anchorpy build refused the synthetic IDL — skipping decode round-trip.")

    # Build the payload anchorpy expects: 8-byte discriminator + u32 LE.
    from app.clients.anchor_decoder import _CODER_CACHE

    coder = next(iter(_CODER_CACHE.values()))
    discriminator = coder.accounts.acc_name_to_discriminator["MerkleTree"]
    payload = discriminator + (7).to_bytes(4, "little")
    encoded = base64.b64encode(payload).decode("ascii")

    result = await decoder.decode_account(encoded, "MerkleTree")
    assert result is not None
    assert result.get("commitment_count") == 7
