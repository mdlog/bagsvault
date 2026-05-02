"""Tests for the claim-fees-then-deposit chained orchestrator.

The service must:

1. Pull unsigned claim transactions from the Bags API (one or many),
   accepting any of the upstream's documented key shapes.
2. Build a deposit ix where the depositor IS the creator wallet — that
   keeps the funds inside the wallet that just received the claim.
3. Return the claim tx batch + the deposit tx in a stable shape.
4. Never sign or broadcast.
"""

from __future__ import annotations

import base64

import pytest
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from app.config import settings
from app.exceptions import ServiceUnavailableError
from app.services.claim_to_deposit_service import ClaimToDepositService


PROGRAM_ID_STR = "AXEc2HCqETrPqzdG8AkErLxfNXDHyeH4cwykvX6qxXvJ"
CREATOR_STR = "11111111111111111111111111111114"
TOKEN_MINT_STR = "11111111111111111111111111111115"
COMMITMENT_HEX = "0x" + ("cd" * 32)


class _FakeBagsClient:
    def __init__(self, response: dict) -> None:
        self._response = response
        self.last_call: tuple[str, str | None] | None = None

    async def build_claim_tx(
        self, creator_wallet: str, token_mint: str | None = None
    ) -> dict:
        self.last_call = (creator_wallet, token_mint)
        return self._response


@pytest.fixture(autouse=True)
def _set_program_id() -> None:
    original = settings.bagsvault_program_id
    settings.bagsvault_program_id = PROGRAM_ID_STR
    yield
    settings.bagsvault_program_id = original


@pytest.mark.asyncio
async def test_build_chain_returns_claim_batch_and_deposit_tx() -> None:
    claim_a = base64.b64encode(b"claim-tx-A").decode("ascii")
    claim_b = base64.b64encode(b"claim-tx-B").decode("ascii")
    fake = _FakeBagsClient(
        {
            "transactions": [claim_a, claim_b],
            "pendingFees": [{"mint": TOKEN_MINT_STR, "amount": "1234"}],
        }
    )
    svc = ClaimToDepositService(bags_client=fake)

    result = await svc.build_chain(
        creator_wallet=CREATOR_STR,
        token_mint=TOKEN_MINT_STR,
        commitment_hex=COMMITMENT_HEX,
    )

    # Shape pin.
    assert set(result.keys()) == {
        "claim_txs",
        "deposit_tx",
        "claim_raw",
        "deposit_program_id",
        "deposit_token_mint",
        "creator_wallet",
    }
    # Claim ordering preserved verbatim.
    assert result["claim_txs"] == [claim_a, claim_b]
    # Deposit tx round-trips through VersionedTransaction.
    raw = base64.b64decode(result["deposit_tx"])
    tx = VersionedTransaction.from_bytes(raw)
    assert len(tx.message.instructions) == 1
    # Echoed addresses are the canonical base58.
    assert result["deposit_program_id"] == PROGRAM_ID_STR
    assert result["deposit_token_mint"] == TOKEN_MINT_STR
    assert result["creator_wallet"] == CREATOR_STR
    # Upstream client received the right inputs.
    assert fake.last_call == (CREATOR_STR, TOKEN_MINT_STR)


@pytest.mark.asyncio
async def test_build_chain_supports_singleton_claim_response() -> None:
    """Bags may return a single string under ``transaction`` instead of a list."""

    only_tx = base64.b64encode(b"only-claim-tx").decode("ascii")
    fake = _FakeBagsClient({"transaction": only_tx})
    svc = ClaimToDepositService(bags_client=fake)

    result = await svc.build_chain(
        creator_wallet=CREATOR_STR,
        token_mint=TOKEN_MINT_STR,
        commitment_hex=COMMITMENT_HEX,
    )
    assert result["claim_txs"] == [only_tx]


@pytest.mark.asyncio
async def test_build_chain_rejects_empty_claim_response() -> None:
    fake = _FakeBagsClient({"unrelated": "value"})
    svc = ClaimToDepositService(bags_client=fake)
    with pytest.raises(ServiceUnavailableError):
        await svc.build_chain(
            creator_wallet=CREATOR_STR,
            token_mint=TOKEN_MINT_STR,
            commitment_hex=COMMITMENT_HEX,
        )


@pytest.mark.asyncio
async def test_build_chain_requires_program_id() -> None:
    settings.bagsvault_program_id = ""
    fake = _FakeBagsClient({"transaction": base64.b64encode(b"x").decode("ascii")})
    svc = ClaimToDepositService(bags_client=fake)
    with pytest.raises(ServiceUnavailableError):
        await svc.build_chain(
            creator_wallet=CREATOR_STR,
            token_mint=TOKEN_MINT_STR,
            commitment_hex=COMMITMENT_HEX,
        )


@pytest.mark.asyncio
async def test_deposit_tx_payer_is_creator_wallet() -> None:
    """The deposit tx must list the creator wallet as the payer slot."""

    only_tx = base64.b64encode(b"only-claim-tx").decode("ascii")
    fake = _FakeBagsClient({"transaction": only_tx})
    svc = ClaimToDepositService(bags_client=fake)

    result = await svc.build_chain(
        creator_wallet=CREATOR_STR,
        token_mint=TOKEN_MINT_STR,
        commitment_hex=COMMITMENT_HEX,
    )

    raw = base64.b64decode(result["deposit_tx"])
    tx = VersionedTransaction.from_bytes(raw)
    # The payer is account_keys[0] in the message header.
    assert tx.message.account_keys[0] == Pubkey.from_string(CREATOR_STR)
