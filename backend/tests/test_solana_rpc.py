"""Tests for the SolanaRpcClient JSON-RPC wrapper."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.solana_rpc import SolanaRpcClient
from app.exceptions import UpstreamError

RPC = "https://rpc.test"


def _ok(result):  # noqa: ANN001 — generic JSON
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def _err(code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}


@pytest.mark.asyncio
async def test_get_health_returns_string() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=_ok("ok"))
        result = await client.get_health()
    assert result == "ok"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_slot_returns_int() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=_ok(12345))
        slot = await client.get_slot()
    assert slot == 12345
    await client.aclose()


@pytest.mark.asyncio
async def test_get_transaction_returns_dict() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    payload = {"slot": 42, "meta": {"err": None}, "transaction": {}}
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=_ok(payload))
        tx = await client.get_transaction("sigsigsig")
    assert tx == payload
    await client.aclose()


@pytest.mark.asyncio
async def test_get_transaction_missing_returns_none() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=_ok(None))
        tx = await client.get_transaction("sigsigsig")
    assert tx is None
    await client.aclose()


@pytest.mark.asyncio
async def test_get_account_info_extracts_value() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    body = _ok({"context": {"slot": 1}, "value": {"data": ["AAA=", "base64"], "owner": "x"}})
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=body)
        account = await client.get_account_info("Pubkey1")
    assert account is not None
    assert account["owner"] == "x"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_account_info_missing_returns_none() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    body = _ok({"context": {"slot": 1}, "value": None})
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=body)
        account = await client.get_account_info("Pubkey1")
    assert account is None
    await client.aclose()


@pytest.mark.asyncio
async def test_get_multiple_accounts_returns_list_with_nones() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    body = _ok(
        {
            "context": {"slot": 1},
            "value": [
                {"data": ["AA==", "base64"], "owner": "o1"},
                None,
            ],
        }
    )
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=body)
        accounts = await client.get_multiple_accounts(["a", "b"])
    assert len(accounts) == 2
    assert accounts[0] is not None and accounts[0]["owner"] == "o1"
    assert accounts[1] is None
    await client.aclose()


@pytest.mark.asyncio
async def test_get_program_accounts_filters_non_dicts() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    body = _ok(
        [
            {"pubkey": "p1", "account": {"data": ["AA==", "base64"]}},
            "garbage-entry",
        ]
    )
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=body)
        result = await client.get_program_accounts("Program111")
    assert len(result) == 1
    assert result[0]["pubkey"] == "p1"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_recent_blockhash_uses_get_latest_blockhash() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    body = _ok({"context": {"slot": 1}, "value": {"blockhash": "BHX", "lastValidBlockHeight": 9}})
    with respx.mock(assert_all_called=True) as router:
        route = router.post(RPC).respond(200, json=body)
        result = await client.get_recent_blockhash()
    assert result == {"blockhash": "BHX", "lastValidBlockHeight": 9}
    sent_body = route.calls.last.request.read().decode()
    assert "getLatestBlockhash" in sent_body
    await client.aclose()


@pytest.mark.asyncio
async def test_send_transaction_returns_signature() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        route = router.post(RPC).respond(200, json=_ok("SignatureXYZ"))
        sig = await client.send_transaction("base64payload", skip_preflight=True)
    assert sig == "SignatureXYZ"
    sent_body = route.calls.last.request.read().decode()
    assert "sendTransaction" in sent_body
    assert "skipPreflight" in sent_body
    await client.aclose()


@pytest.mark.asyncio
async def test_jsonrpc_error_envelope_raises_upstream() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(200, json=_err(-32000, "bad"))
        with pytest.raises(UpstreamError) as ei:
            await client.get_slot()
    assert ei.value.details["upstream"] == "solana_rpc"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_5xx_raises_upstream() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).respond(503, text="overloaded")
        with pytest.raises(UpstreamError) as ei:
            await client.get_slot()
    assert ei.value.details["status_code"] == 503
    await client.aclose()


@pytest.mark.asyncio
async def test_network_error_raises_upstream() -> None:
    client = SolanaRpcClient(rpc_url=RPC)
    with respx.mock(assert_all_called=True) as router:
        router.post(RPC).mock(side_effect=httpx.ConnectError("dns fail"))
        with pytest.raises(UpstreamError):
            await client.get_slot()
    await client.aclose()
