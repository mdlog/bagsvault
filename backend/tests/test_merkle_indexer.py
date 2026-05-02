"""Tests for the on-chain Merkle-root indexer."""

from __future__ import annotations

import base64
import struct
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.merkle_indexer import MerkleIndexer


def _build_account_data(root: bytes, commitment_count: int) -> str:
    """Build a base64 payload matching MerkleIndexer's layout assumption."""

    discriminator = b"\x00" * 8
    bump = b"\x01"
    count = struct.pack("<I", commitment_count)
    # Pad with extra recent_roots buffer (10 * 32 bytes) so length is realistic.
    recent = b"\x00" * (10 * 32)
    raw = discriminator + bump + count + root + recent
    return base64.b64encode(raw).decode("ascii")


def _make_db_with_roots(items: list[dict]) -> MagicMock:
    db = MagicMock(name="db")
    db.merkle_roots = MagicMock(name="merkle_roots")
    db.merkle_roots.insert_one = AsyncMock()
    db.merkle_roots.find_one = AsyncMock(return_value=None)

    class _Cursor:
        def __init__(self, items: list[dict]) -> None:
            self._items = list(items)

        def sort(self, *_a, **_kw) -> "_Cursor":  # noqa: ANN001, ANN003
            return self

        def limit(self, *_a, **_kw) -> "_Cursor":  # noqa: ANN001, ANN003
            return self

        def __aiter__(self) -> "_Cursor":
            return self

        async def __anext__(self) -> dict:
            if not self._items:
                raise StopAsyncIteration
            return self._items.pop(0)

    db.merkle_roots.find = MagicMock(return_value=_Cursor(items))
    return db


@pytest.mark.asyncio
async def test_sync_now_noop_when_program_id_missing(monkeypatch) -> None:
    monkeypatch.setattr("app.services.merkle_indexer.settings.bagsvault_program_id", "")
    rpc = MagicMock(name="rpc")
    rpc.get_account_info = AsyncMock()
    db = _make_db_with_roots([])
    indexer = MerkleIndexer(rpc=rpc, db=db)

    result = await indexer.sync_now()

    assert result is None
    rpc.get_account_info.assert_not_called()


@pytest.mark.asyncio
async def test_sync_now_decodes_root_and_inserts(monkeypatch) -> None:
    program_id = "BPFLoaderUpgradeab1e11111111111111111111111"
    monkeypatch.setattr("app.services.merkle_indexer.settings.bagsvault_program_id", program_id)
    root_bytes = bytes(range(32))
    encoded = _build_account_data(root_bytes, commitment_count=7)

    rpc = MagicMock(name="rpc")
    rpc.get_account_info = AsyncMock(
        return_value={"data": [encoded, "base64"], "owner": program_id, "rentEpoch": 99}
    )
    db = _make_db_with_roots([])
    indexer = MerkleIndexer(rpc=rpc, db=db)

    record = await indexer.sync_now()

    assert record is not None
    assert record.root == root_bytes.hex()
    assert record.commitment_count == 7
    assert record.source == "indexed"
    db.merkle_roots.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_now_handles_missing_pda(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.merkle_indexer.settings.bagsvault_program_id",
        "BPFLoaderUpgradeab1e11111111111111111111111",
    )
    rpc = MagicMock(name="rpc")
    rpc.get_account_info = AsyncMock(return_value=None)
    db = _make_db_with_roots([])
    indexer = MerkleIndexer(rpc=rpc, db=db)

    record = await indexer.sync_now()

    assert record is None
    db.merkle_roots.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_sync_now_handles_short_account_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.merkle_indexer.settings.bagsvault_program_id",
        "BPFLoaderUpgradeab1e11111111111111111111111",
    )
    short_payload = base64.b64encode(b"too-short").decode("ascii")
    rpc = MagicMock(name="rpc")
    rpc.get_account_info = AsyncMock(return_value={"data": [short_payload, "base64"], "owner": "x"})
    db = _make_db_with_roots([])
    indexer = MerkleIndexer(rpc=rpc, db=db)

    record = await indexer.sync_now()

    assert record is None
    db.merkle_roots.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_get_recent_roots_reads_from_cache() -> None:
    items = [
        {
            "root": "ff" * 32,
            "commitment_count": 5,
            "block_height": None,
            "indexed_at": datetime.now(timezone.utc),
            "source": "indexed",
        },
        {
            "root": "ee" * 32,
            "commitment_count": 4,
            "block_height": None,
            "indexed_at": datetime.now(timezone.utc),
            "source": "indexed",
        },
    ]
    db = _make_db_with_roots(items)
    indexer = MerkleIndexer(rpc=MagicMock(), db=db)

    roots = await indexer.get_recent_roots(limit=5)

    assert len(roots) == 2
    assert roots[0].root == "ff" * 32


@pytest.mark.asyncio
async def test_get_current_root_returns_latest() -> None:
    db = MagicMock(name="db")
    db.merkle_roots = MagicMock(name="merkle_roots")
    db.merkle_roots.find_one = AsyncMock(
        return_value={
            "root": "ab" * 32,
            "commitment_count": 1,
            "block_height": None,
            "indexed_at": datetime.now(timezone.utc),
            "source": "indexed",
        }
    )
    indexer = MerkleIndexer(rpc=MagicMock(), db=db)

    current = await indexer.get_current_root()

    assert current is not None
    assert current.root == "ab" * 32


@pytest.mark.asyncio
async def test_get_current_root_returns_none_when_empty() -> None:
    db = MagicMock(name="db")
    db.merkle_roots = MagicMock(name="merkle_roots")
    db.merkle_roots.find_one = AsyncMock(return_value=None)
    indexer = MerkleIndexer(rpc=MagicMock(), db=db)

    current = await indexer.get_current_root()

    assert current is None
