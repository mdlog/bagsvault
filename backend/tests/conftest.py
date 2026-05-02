"""Shared pytest fixtures."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeAggregateCursor:
    """Minimal async iterator returned by db.collection.aggregate(...)."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = list(items)

    def __aiter__(self) -> "_FakeAggregateCursor":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


@pytest.fixture
def fake_db() -> MagicMock:
    """A MagicMock standing in for AsyncIOMotorDatabase + risk_scans collection."""

    db = MagicMock(name="db")
    db.risk_scans = MagicMock(name="risk_scans")
    db.risk_scans.update_one = AsyncMock()
    db.risk_scans.find_one = AsyncMock(return_value=None)
    db.risk_scans.aggregate = MagicMock(return_value=_FakeAggregateCursor([]))
    db.idempotency_keys = MagicMock(name="idempotency_keys")
    db.idempotency_keys.find_one = AsyncMock(return_value=None)
    db.idempotency_keys.insert_one = AsyncMock()
    db.command = AsyncMock(return_value={"ok": 1})
    return db


@pytest.fixture
def fake_aggregate_cursor() -> type[_FakeAggregateCursor]:
    return _FakeAggregateCursor
