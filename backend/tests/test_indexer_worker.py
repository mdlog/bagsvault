"""Tests for the background :class:`IndexerWorker` lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.indexer_worker import (
    IndexerWorker,
    get_indexer_worker,
    reset_indexer_worker,
    status_snapshot,
)


def _make_indexer(side_effects: list = None) -> AsyncMock:  # noqa: ANN001
    """Build a stub MerkleIndexer whose ``sync_now`` walks ``side_effects``."""

    indexer = AsyncMock()
    if side_effects is None:
        indexer.sync_now = AsyncMock(return_value=None)
    else:
        indexer.sync_now = AsyncMock(side_effect=list(side_effects))
    return indexer


@pytest.mark.asyncio
async def test_worker_ticks_and_records_last_sync_at() -> None:
    indexer = _make_indexer([None, None])
    worker = IndexerWorker(indexer=indexer, interval_seconds=1)

    await worker.start()
    # Give the loop a chance to run at least one tick.
    for _ in range(20):
        if indexer.sync_now.await_count >= 1:
            break
        await asyncio.sleep(0.05)

    assert worker.is_running
    assert indexer.sync_now.await_count >= 1
    assert worker.last_sync_at is not None
    assert worker.last_sync_error is None

    await worker.stop()
    assert not worker.is_running


@pytest.mark.asyncio
async def test_worker_continues_after_exception() -> None:
    boom = RuntimeError("rpc kaboom")
    # First tick raises, subsequent ticks succeed.
    indexer = _make_indexer([boom, None, None])
    worker = IndexerWorker(indexer=indexer, interval_seconds=1)

    await worker.start()
    for _ in range(40):
        if indexer.sync_now.await_count >= 2:
            break
        await asyncio.sleep(0.05)

    # The loop must have continued past the failing tick.
    assert indexer.sync_now.await_count >= 2
    # Last successful tick clears the error and stamps last_sync_at.
    assert worker.last_sync_error is None
    assert worker.last_sync_at is not None

    await worker.stop()


@pytest.mark.asyncio
async def test_worker_records_error_on_failed_tick() -> None:
    boom = RuntimeError("transient")
    # Make every tick raise — the worker should never crash.
    indexer = AsyncMock()
    indexer.sync_now = AsyncMock(side_effect=boom)
    worker = IndexerWorker(indexer=indexer, interval_seconds=1)

    await worker.start()
    for _ in range(40):
        if indexer.sync_now.await_count >= 1:
            break
        await asyncio.sleep(0.05)

    assert worker.last_sync_error == "transient"
    assert worker.last_sync_at is None  # never succeeded

    await worker.stop()


@pytest.mark.asyncio
async def test_worker_start_is_idempotent() -> None:
    indexer = _make_indexer()
    worker = IndexerWorker(indexer=indexer, interval_seconds=1)

    await worker.start()
    first_task = worker._task  # type: ignore[attr-defined]
    await worker.start()
    second_task = worker._task  # type: ignore[attr-defined]
    assert first_task is second_task

    await worker.stop()


@pytest.mark.asyncio
async def test_worker_stop_when_never_started_is_noop() -> None:
    worker = IndexerWorker(indexer=_make_indexer(), interval_seconds=1)
    await worker.stop()  # must not raise


@pytest.mark.asyncio
async def test_worker_constructor_rejects_nonpositive_interval() -> None:
    with pytest.raises(ValueError):
        IndexerWorker(indexer=_make_indexer(), interval_seconds=0)


@pytest.mark.asyncio
async def test_get_indexer_worker_singleton(monkeypatch) -> None:
    reset_indexer_worker()
    indexer = _make_indexer()
    w1 = get_indexer_worker(indexer=indexer, interval_seconds=5)
    w2 = get_indexer_worker(indexer=indexer, interval_seconds=5)
    assert w1 is w2
    reset_indexer_worker()


@pytest.mark.asyncio
async def test_status_snapshot_reflects_state() -> None:
    reset_indexer_worker()
    indexer = _make_indexer()
    worker = get_indexer_worker(indexer=indexer, interval_seconds=1)

    snap_before = status_snapshot()
    assert snap_before["running"] is False
    assert snap_before["last_sync_at"] is None

    await worker.start()
    for _ in range(20):
        if indexer.sync_now.await_count >= 1:
            break
        await asyncio.sleep(0.05)

    snap_after = status_snapshot()
    assert snap_after["running"] is True
    assert snap_after["last_sync_at"] is not None

    await worker.stop()
    reset_indexer_worker()


@pytest.mark.asyncio
async def test_run_with_ws_records_each_root() -> None:
    """``run_with_ws`` must update last_sync_at per yielded root."""

    from app.models.merkle import MerkleRoot

    class _FakeIndexer:
        async def subscribe_root_updates(self, _ws):  # noqa: ANN001
            yield MerkleRoot(root="aa" * 32, commitment_count=1, source="indexed")
            yield MerkleRoot(root="bb" * 32, commitment_count=2, source="indexed")

    worker = IndexerWorker(indexer=_FakeIndexer(), interval_seconds=1)  # type: ignore[arg-type]
    await worker.run_with_ws(ws=None)  # type: ignore[arg-type]

    assert worker.last_sync_at is not None
    assert worker.last_sync_error is None
