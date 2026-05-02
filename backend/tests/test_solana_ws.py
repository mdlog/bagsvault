"""Tests for the Solana WebSocket client.

We never connect to a real node — instead we monkeypatch
``solana.rpc.websocket_api.connect`` with a fake async-context-manager
that emits scripted notifications.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.clients import solana_ws as ws_module
from app.clients.solana_ws import SolanaWsClient
from app.exceptions import ServiceUnavailableError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeNotification:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_json(self) -> str:
        import json

        return json.dumps(self._payload)


class _FakeWs:
    """Minimal stand-in for ``SolanaWsClientProtocol`` used in tests."""

    def __init__(self, scripted_messages: list[Any]) -> None:
        self._messages = list(scripted_messages)
        self.account_subscribe_called_with: tuple[Any, str | None] | None = None
        self.logs_subscribe_called_with: Any = None

    async def account_subscribe(self, pubkey, encoding=None):  # noqa: ANN001
        self.account_subscribe_called_with = (pubkey, encoding)

    async def logs_subscribe(self, filter_):  # noqa: ANN001
        self.logs_subscribe_called_with = filter_

    def __aiter__(self) -> "_FakeWs":
        return self

    async def __anext__(self) -> Any:
        if not self._messages:
            raise StopAsyncIteration
        item = self._messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeConnect:
    """Async context manager + factory mirroring ``solana_ws.connect``."""

    def __init__(self, scripts: list[list[Any]]) -> None:
        # Each call to ``connect`` consumes one script (list of msgs).
        self._scripts = list(scripts)
        self.opened: list[_FakeWs] = []
        self.urls: list[str] = []

    def __call__(self, url: str, **_: Any) -> "_FakeConnect":
        self.urls.append(url)
        self._current = _FakeWs(self._scripts.pop(0) if self._scripts else [])
        self.opened.append(self._current)
        return self

    async def __aenter__(self) -> _FakeWs:
        return self._current

    async def __aexit__(self, *_exc: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_invalid_url_raises_service_unavailable() -> None:
    with pytest.raises(ServiceUnavailableError):
        SolanaWsClient(ws_url="")
    with pytest.raises(ServiceUnavailableError):
        SolanaWsClient(ws_url="https://not-ws.example")


def test_logs_filter_mentions_requires_pubkey() -> None:
    client = SolanaWsClient(ws_url="wss://ws.test")
    with pytest.raises(ServiceUnavailableError):
        client._logs_filter("mentions", None)


def test_logs_filter_unknown_kind_raises() -> None:
    client = SolanaWsClient(ws_url="wss://ws.test")
    with pytest.raises(ServiceUnavailableError):
        client._logs_filter("does-not-exist", None)


@pytest.mark.asyncio
async def test_subscribe_account_yields_parsed_notifications(monkeypatch) -> None:
    payload = {
        "result": {
            "context": {"slot": 1},
            "value": {"data": ["AAA=", "base64"], "owner": "x"},
        }
    }
    msgs = [[_FakeNotification(payload)]]
    fake_connect = _FakeConnect([msgs])

    monkeypatch.setattr("solana.rpc.websocket_api.connect", fake_connect)

    client = SolanaWsClient(ws_url="wss://ws.test")
    pubkey = "BPFLoaderUpgradeab1e11111111111111111111111"

    received: list[dict[str, Any]] = []
    agen = client.subscribe_account(pubkey)
    try:
        async for item in agen:
            received.append(item)
            if len(received) >= 1:
                break
    finally:
        await agen.aclose()

    assert len(received) == 1
    assert received[0] == payload
    assert fake_connect.opened[0].account_subscribe_called_with is not None


@pytest.mark.asyncio
async def test_subscribe_account_reconnects_on_disconnect(monkeypatch) -> None:
    """First connection drops with an error; the loop reconnects + delivers."""

    err_msgs = [ConnectionError("boom")]
    good_msgs = [[_FakeNotification({"result": {"value": {"data": ["BB==", "base64"]}}})]]
    fake_connect = _FakeConnect([err_msgs, good_msgs])

    monkeypatch.setattr("solana.rpc.websocket_api.connect", fake_connect)
    # Speed up the reconnect backoff so the test stays fast.
    monkeypatch.setattr(ws_module, "_RECONNECT_INITIAL_BACKOFF", 0.01)
    monkeypatch.setattr(ws_module, "_RECONNECT_MAX_BACKOFF", 0.05)

    client = SolanaWsClient(ws_url="wss://ws.test")
    pubkey = "BPFLoaderUpgradeab1e11111111111111111111111"

    received: list[dict[str, Any]] = []
    agen = client.subscribe_account(pubkey)
    try:
        # The reconnect path must eventually deliver the second script.
        async def _take_one() -> None:
            async for item in agen:
                received.append(item)
                break

        await asyncio.wait_for(_take_one(), timeout=2.0)
    finally:
        await agen.aclose()

    assert len(received) == 1
    assert "value" in received[0].get("result", {})
    # Two ``connect`` calls — the failed one + the successful one.
    assert len(fake_connect.opened) == 2


@pytest.mark.asyncio
async def test_subscribe_logs_yields_payloads(monkeypatch) -> None:
    payload = {"result": {"value": {"signature": "abc", "logs": ["log1"]}}}
    fake_connect = _FakeConnect([[[_FakeNotification(payload)]]])
    monkeypatch.setattr("solana.rpc.websocket_api.connect", fake_connect)

    client = SolanaWsClient(ws_url="wss://ws.test")
    received: list[dict[str, Any]] = []

    agen = client.subscribe_logs(filter_kind="all")
    try:
        async for item in agen:
            received.append(item)
            break
    finally:
        await agen.aclose()

    assert received == [payload]
    assert fake_connect.opened[0].logs_subscribe_called_with is not None


@pytest.mark.asyncio
async def test_to_dict_falls_back_when_to_json_unavailable() -> None:
    client = SolanaWsClient(ws_url="wss://ws.test")

    class _Plain:
        def __repr__(self) -> str:
            return "plain-obj"

    out = client._to_dict(_Plain())
    assert out == {"raw": "plain-obj"}
