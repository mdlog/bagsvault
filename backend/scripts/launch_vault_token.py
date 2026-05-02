"""Operator CLI: build the unsigned $VAULT token-launch transaction.

This script is idempotent. It NEVER signs or broadcasts — it only asks
the Bags API to build an unsigned transaction and prints it for the
operator to sign with their wallet (Phantom etc).

Usage::

    python -m scripts.launch_vault_token

Steps:

1. Load settings.
2. If ``VAULT_TOKEN_MINT`` is already set, warn and exit 0 (idempotent).
3. If ``BAGS_API_KEY`` is empty, error and exit 1.
4. Load the token-authority Solana keypair, derive its base58 pubkey for
   display (the file is NOT used to sign).
5. Call ``BagsAPIClient.build_token_launch(...)`` and print the unsigned
   transaction + next-step instructions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import typer
from solders.keypair import Keypair  # type: ignore[import-not-found]

from app.clients.bags_api import BagsAPIClient
from app.config import settings
from app.exceptions import BagsVaultError

logger = logging.getLogger(__name__)

DEFAULT_NAME = "BagsVault Governance"
DEFAULT_SYMBOL = "VAULT"
DEFAULT_DECIMALS = 9
DEFAULT_SUPPLY = 1_000_000_000  # 1B whole tokens (multiplied by 10**decimals upstream)


app = typer.Typer(add_completion=False, no_args_is_help=False)


def _load_authority_pubkey(keypair_path: Path) -> str:
    """Read a Solana JSON keypair (list of 64 ints) and return base58 pubkey."""

    raw = keypair_path.read_text()
    secret = json.loads(raw)
    if not isinstance(secret, list):
        raise typer.BadParameter(
            f"Expected a JSON array in {keypair_path}, got {type(secret).__name__}."
        )
    secret_bytes = bytes(secret)
    keypair = Keypair.from_bytes(secret_bytes)
    return str(keypair.pubkey())


async def _build(
    *,
    name: str,
    symbol: str,
    decimals: int,
    supply: int,
    authority_pubkey: str,
) -> dict[str, Any]:
    client = BagsAPIClient()
    try:
        return await client.build_token_launch(
            name=name,
            symbol=symbol,
            decimals=decimals,
            supply=supply,
            authority_pubkey=authority_pubkey,
        )
    finally:
        await client.aclose()


@app.command()
def main(
    name: str = typer.Option(DEFAULT_NAME, help="Token display name."),
    symbol: str = typer.Option(DEFAULT_SYMBOL, help="Token ticker symbol."),
    decimals: int = typer.Option(DEFAULT_DECIMALS, help="Decimals (SPL standard: 9)."),
    supply: int = typer.Option(DEFAULT_SUPPLY, help="Initial whole-token supply."),
) -> None:
    """Build the unsigned $VAULT launch transaction."""

    logging.basicConfig(level=settings.log_level, format="%(message)s")

    if settings.vault_token_mint:
        typer.echo(
            f"VAULT_TOKEN_MINT is already set ({settings.vault_token_mint}). "
            "Nothing to do — this script is idempotent."
        )
        raise typer.Exit(code=0)

    if not settings.bags_api_key:
        typer.secho(
            "BAGS_API_KEY is empty. Set it in .env before running this script.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    keypair_path = settings.keypair_path(settings.solana_token_authority_keypair)
    if not keypair_path.exists():
        typer.secho(
            f"Token-authority keypair not found at {keypair_path}. "
            "Run scripts/gen_keypair.py first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    authority_pubkey = _load_authority_pubkey(keypair_path)
    typer.echo(f"Using token-authority pubkey: {authority_pubkey}")

    try:
        result = asyncio.run(
            _build(
                name=name,
                symbol=symbol,
                decimals=decimals,
                supply=supply,
                authority_pubkey=authority_pubkey,
            )
        )
    except BagsVaultError as exc:
        typer.secho(f"Bags API error: {exc.message}", fg=typer.colors.RED, err=True)
        if exc.details:
            typer.secho(json.dumps(exc.details, indent=2), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("\n=== Unsigned launch transaction ===")
    typer.echo(json.dumps(result, indent=2))
    typer.echo("\nNext steps:")
    typer.echo("  1. Sign and send the transaction above via your wallet (Phantom, Solflare, ...).")
    typer.echo("  2. Set VAULT_TOKEN_MINT=<mint_pubkey> in your .env file.")
    typer.echo("  3. Restart the backend.")


if __name__ == "__main__":
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI safety net
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        sys.exit(3)
