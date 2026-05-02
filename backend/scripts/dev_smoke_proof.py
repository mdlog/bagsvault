"""Operator dev helper: produce a real Groth16 withdraw proof for the
empty tree and dump it as hex.

The script wires up :class:`ZkProofService` against the real ``nargo``
+ ``bb`` toolchain (it refuses to run in stub mode — that's what
``test_zk_proof_service.py`` is for) and prints a proof + public-input
vector that can be pasted into a manual ``withdraw`` instruction to
validate the on-chain verifier accepts ceremony output.

Usage::

    cd backend
    ZK_PROOF_STUB_MODE=false python -m scripts.dev_smoke_proof

Witness is the simplest possible one: leaf at index 0, all-zero Merkle
path, deterministic nullifier/secret. The Merkle root is recomputed by
:meth:`ZkProofService.merkle_root_from_path` and emitted alongside the
proof so the caller has every ingredient the on-chain ix expects.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import typer
from solders.pubkey import Pubkey  # type: ignore[import-not-found]

from app.config import settings
from app.services.zk_proof_service import (
    WithdrawProofInput,
    ZkProofService,
    reset_zk_proof_service,
)

logger = logging.getLogger(__name__)

DEFAULT_DENOMINATION = 1_000_000_000  # 1 SOL in lamports
DEFAULT_NULLIFIER = 1
DEFAULT_SECRET = 2

app = typer.Typer(add_completion=False, no_args_is_help=False)


def _build_payload(
    nullifier: int,
    secret: int,
    amount: int,
    recipient: Pubkey,
    relayer: Pubkey,
) -> WithdrawProofInput:
    """Construct the witness for the empty-tree leaf-0 case."""

    return WithdrawProofInput(
        nullifier=nullifier,
        secret=secret,
        amount=amount,
        leaf_index=0,
        merkle_path=[0] * 20,
        is_left=[1] * 20,
        recipient_pubkey_bytes=bytes(recipient),
        relayer_pubkey_bytes=bytes(relayer),
    )


async def _run(
    nullifier: int,
    secret: int,
    amount: int,
    recipient: Pubkey,
    relayer: Pubkey,
) -> None:
    reset_zk_proof_service()
    svc = ZkProofService(stub_mode=False)
    if not svc._toolchain_available():  # noqa: SLF001 — diagnostic shortcut
        typer.secho(
            "nargo / bb not on PATH — install Noir + Barretenberg before "
            "running this script. See circuits/bagsvault_withdraw/README.md.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    payload = _build_payload(nullifier, secret, amount, recipient, relayer)
    typer.echo(">>> generating real Groth16 proof (this can take a while)…")
    result = await svc.generate_withdraw_proof(payload)

    typer.echo("\n=== WithdrawProofResult ===")
    typer.echo(f"  root            = {result.root_hex}")
    typer.echo(f"  nullifier_hash  = {result.nullifier_hash_hex}")
    typer.echo(f"  commitment      = {result.commitment_hex}")
    typer.echo("  public_inputs   =")
    for i, value in enumerate(result.public_inputs_hex):
        typer.echo(f"    [{i}] {value}")
    typer.echo("\n  proof (256 bytes hex) =")
    typer.echo(f"  {result.proof_hex}")


@app.command()
def main(
    amount: int = typer.Option(
        DEFAULT_DENOMINATION,
        "--amount",
        help="Withdrawal denomination in lamports (must match the pool config).",
    ),
    nullifier: int = typer.Option(
        DEFAULT_NULLIFIER,
        "--nullifier",
        help="Witness nullifier (any positive integer; deterministic by default).",
    ),
    secret: int = typer.Option(
        DEFAULT_SECRET,
        "--secret",
        help="Witness secret (any positive integer; deterministic by default).",
    ),
    recipient: str = typer.Option(
        str(Pubkey.default()),
        "--recipient",
        help="Solana base58 pubkey to bind the proof to.",
    ),
    relayer: str = typer.Option(
        str(Pubkey.default()),
        "--relayer",
        help="Solana base58 pubkey of the relayer that will submit the tx.",
    ),
) -> None:
    """Produce a real withdraw proof against the empty tree, leaf index 0."""

    logging.basicConfig(level=settings.log_level, format="%(message)s")

    if settings.zk_proof_stub_mode:
        typer.secho(
            "ZK_PROOF_STUB_MODE is true — refusing to run. The whole point "
            "of this script is to exercise the real nargo/bb toolchain. "
            "Set ZK_PROOF_STUB_MODE=false (e.g. export it in your shell) "
            "and re-run.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        recipient_pubkey = Pubkey.from_string(recipient)
        relayer_pubkey = Pubkey.from_string(relayer)
    except Exception as exc:  # noqa: BLE001 — solders may raise plain ValueError
        raise typer.BadParameter(
            f"invalid pubkey ({exc}). Pass a base58-encoded Solana address."
        ) from exc

    asyncio.run(_run(nullifier, secret, amount, recipient_pubkey, relayer_pubkey))
    typer.echo("\nDone.")


if __name__ == "__main__":
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI safety net
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        sys.exit(2)
