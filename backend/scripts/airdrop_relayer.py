"""Operator CLI: request a SOL airdrop for the relayer (and friends).

Devnet faucet only. The script refuses to run when
``SOLANA_CLUSTER=mainnet-beta`` so a typo can't burn real funds.

Usage::

    python -m scripts.airdrop_relayer
    python -m scripts.airdrop_relayer --amount-sol 2 --target all

``--target`` accepts ``relayer`` (default), ``treasury``,
``token_authority``, or ``all``. ``--amount-sol`` is capped at 2 — the
public devnet faucet rejects larger requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from solders.keypair import Keypair  # type: ignore[import-not-found]

from app.clients.solana_rpc import SolanaRpcClient
from app.config import settings
from app.exceptions import BagsVaultError

logger = logging.getLogger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000
DEVNET_FAUCET_MAX_SOL = 2

app = typer.Typer(add_completion=False, no_args_is_help=False)


class Target(str, Enum):
    """Wallet to airdrop to. ``all`` fans out to every configured wallet."""

    relayer = "relayer"
    treasury = "treasury"
    token_authority = "token_authority"
    all = "all"


def _load_pubkey(keypair_path: Path) -> str:
    """Read a Solana JSON keypair (list of 64 ints) and return base58 pubkey."""

    raw = keypair_path.read_text()
    secret = json.loads(raw)
    if not isinstance(secret, list):
        raise typer.BadParameter(
            f"Expected a JSON array in {keypair_path}, got {type(secret).__name__}."
        )
    keypair = Keypair.from_bytes(bytes(secret))
    return str(keypair.pubkey())


def _resolve_targets(target: Target) -> list[tuple[str, Path]]:
    """Map ``target`` to ``[(label, keypair_path), ...]``."""

    mapping = {
        "relayer": settings.keypair_path(settings.solana_relayer_keypair),
        "treasury": settings.keypair_path(settings.solana_treasury_keypair),
        "token_authority": settings.keypair_path(settings.solana_token_authority_keypair),
    }
    if target is Target.all:
        return [(name, path) for name, path in mapping.items()]
    return [(target.value, mapping[target.value])]


async def _request_airdrop(client: SolanaRpcClient, pubkey: str, lamports: int) -> str:
    """Fire ``requestAirdrop`` and return the transaction signature."""

    # SolanaRpcClient exposes ``_call`` for arbitrary methods; we reach
    # through it deliberately rather than padding the public API with a
    # one-off ``request_airdrop`` helper.
    result: Any = await client._call(  # noqa: SLF001 — intentional CLI shortcut
        "requestAirdrop",
        [pubkey, lamports, {"commitment": settings.solana_commitment}],
    )
    if not isinstance(result, str):
        raise typer.Exit(code=2)
    return result


async def _confirm(client: SolanaRpcClient, signature: str) -> str:
    """Best-effort wait for the airdrop tx to be visible to the node."""

    for _ in range(20):
        tx = await client.get_transaction(signature)
        if tx is not None:
            err = tx.get("meta", {}).get("err") if isinstance(tx.get("meta"), dict) else None
            return "failed" if err else "confirmed"
        await asyncio.sleep(1.5)
    return "pending"


async def _run(target: Target, lamports: int) -> None:
    client = SolanaRpcClient()
    try:
        for label, path in _resolve_targets(target):
            if not path.exists():
                typer.secho(
                    f"  skip {label}: keypair not found at {path}",
                    fg=typer.colors.YELLOW,
                )
                continue
            pubkey = _load_pubkey(path)
            typer.echo(f"\n>>> {label}")
            typer.echo(f"  pubkey:    {pubkey}")
            try:
                signature = await _request_airdrop(client, pubkey, lamports)
            except BagsVaultError as exc:
                typer.secho(f"  airdrop failed: {exc.message}", fg=typer.colors.RED, err=True)
                if exc.details:
                    typer.secho(json.dumps(exc.details, indent=2), fg=typer.colors.RED, err=True)
                continue
            typer.echo(f"  signature: {signature}")
            status = await _confirm(client, signature)
            color = (
                typer.colors.GREEN
                if status == "confirmed"
                else typer.colors.YELLOW if status == "pending" else typer.colors.RED
            )
            typer.secho(f"  status:    {status}", fg=color)
    finally:
        await client.aclose()


@app.command()
def main(
    amount_sol: float = typer.Option(
        1.0,
        "--amount-sol",
        help="SOL to request (devnet faucet caps individual requests at 2).",
    ),
    target: Target = typer.Option(
        Target.relayer,
        "--target",
        case_sensitive=False,
        help="Which wallet to fund: relayer | treasury | token_authority | all.",
    ),
) -> None:
    """Request a devnet SOL airdrop for one or more BagsVault wallets."""

    logging.basicConfig(level=settings.log_level, format="%(message)s")

    if settings.solana_cluster == "mainnet-beta":
        raise typer.BadParameter("Refusing to run on mainnet-beta — airdrops are devnet-only.")

    if amount_sol <= 0 or amount_sol > DEVNET_FAUCET_MAX_SOL:
        raise typer.BadParameter(
            f"--amount-sol must be in (0, {DEVNET_FAUCET_MAX_SOL}]; got {amount_sol}."
        )

    lamports = int(amount_sol * LAMPORTS_PER_SOL)
    typer.echo(
        f"Requesting airdrop on cluster={settings.solana_cluster} "
        f"(rpc={settings.solana_rpc_url}) target={target.value} amount={amount_sol} SOL"
    )

    try:
        asyncio.run(_run(target, lamports))
    except BagsVaultError as exc:
        typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
        if exc.details:
            typer.secho(json.dumps(exc.details, indent=2), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("\nDone.")


if __name__ == "__main__":
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI safety net
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        sys.exit(2)
