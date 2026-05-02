"""Operator CLI: seed the relayer registry.

Always upserts this node (with the relayer keypair's pubkey) so the
running backend can advertise itself in ``/api/relayers``. By default
also upserts the six demo relayers visible in the frontend mockup
(``frontend/src/pages/Relayers.jsx``) so the leaderboard isn't empty
during demos. Pass ``--no-with-demo`` to opt out for production
deployments.

Usage::

    python -m scripts.seed_relayers
    python -m scripts.seed_relayers --no-with-demo
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from typing import Any

import base58
import typer

from app.clients.solana_signer import SolanaSignerClient
from app.config import settings
from app.database import db
from app.exceptions import BagsVaultError
from app.models.relayer import Relayer
from app.services.relayer_service import RelayerService

logger = logging.getLogger(__name__)

app = typer.Typer(add_completion=False, no_args_is_help=False)


# Demo relayers mirror the frontend's hard-coded mock list. Real
# operator nodes replace these by registering their own ``relayer_id``.
DEMO_RELAYERS: list[dict[str, Any]] = [
    {
        "relayer_id": "rly-01",
        "name": "NovaRelay",
        "operator": "nova.sol",
        "region": "US-East",
        "fee_bps": 15,
        "ping_ms": 42,
        "uptime_pct": 99.98,
        "jobs_24h": 12_840,
        "volume_24h_lamports": 412_000_000_000_000,
    },
    {
        "relayer_id": "rly-02",
        "name": "GhostNode",
        "operator": "ghost.sol",
        "region": "EU-West",
        "fee_bps": 20,
        "ping_ms": 58,
        "uptime_pct": 99.91,
        "jobs_24h": 8_721,
        "volume_24h_lamports": 287_000_000_000_000,
    },
    {
        "relayer_id": "rly-03",
        "name": "PhantomProxy",
        "operator": "phantom.sol",
        "region": "Asia-Pacific",
        "fee_bps": 12,
        "ping_ms": 71,
        "uptime_pct": 99.74,
        "jobs_24h": 6_104,
        "volume_24h_lamports": 198_000_000_000_000,
    },
    {
        "relayer_id": "rly-04",
        "name": "ZeroGateway",
        "operator": "zerog.sol",
        "region": "US-West",
        "fee_bps": 18,
        "ping_ms": 38,
        "uptime_pct": 99.99,
        "jobs_24h": 15_204,
        "volume_24h_lamports": 521_000_000_000_000,
    },
    {
        "relayer_id": "rly-05",
        "name": "SilentBroadcast",
        "operator": "silent.sol",
        "region": "EU-Central",
        "fee_bps": 22,
        "ping_ms": 82,
        "uptime_pct": 99.67,
        "jobs_24h": 4_412,
        "volume_24h_lamports": 142_000_000_000_000,
    },
    {
        "relayer_id": "rly-06",
        "name": "VaultPipe",
        "operator": "vault.sol",
        "region": "US-East",
        "fee_bps": 14,
        "ping_ms": 49,
        "uptime_pct": 99.95,
        "jobs_24h": 11_020,
        "volume_24h_lamports": 358_000_000_000_000,
    },
]


def _deterministic_pubkey(seed: str) -> str:
    """Deterministic-but-fake base58 pubkey derived from ``seed``.

    Using sha256 keeps the value stable across runs (so re-seeding is a
    no-op) without ever producing a key the operator can sign with.
    """

    digest = hashlib.sha256(f"seed-{seed}".encode("utf-8")).digest()
    return base58.b58encode(digest).decode("ascii")[:44]


async def _seed(*, with_demo: bool) -> list[Relayer]:
    service = RelayerService(db=db)
    seeded: list[Relayer] = []

    # 1) This node — derived from settings + the on-disk relayer keypair.
    signer = SolanaSignerClient()
    self_pubkey = signer.pubkey()
    self_relayer = Relayer(
        relayer_id=f"rly-self-{self_pubkey[:4]}",
        name=settings.relayer_name,
        operator=self_pubkey,
        pubkey=self_pubkey,
        region=settings.relayer_region,
        fee_bps=settings.relayer_fee_bps,
        ping_ms=0,
        uptime_pct=100.0,
    )
    seeded.append(await service.upsert(self_relayer))
    typer.echo(f"  upsert {self_relayer.relayer_id} ({self_relayer.name}) pubkey={self_pubkey}")

    # 2) Demo relayers (deterministic fake pubkeys).
    if with_demo:
        for entry in DEMO_RELAYERS:
            pubkey = _deterministic_pubkey(entry["relayer_id"])
            relayer = Relayer(
                relayer_id=entry["relayer_id"],
                name=entry["name"],
                operator=entry["operator"],
                pubkey=pubkey,
                region=entry["region"],
                fee_bps=entry["fee_bps"],
                ping_ms=entry["ping_ms"],
                uptime_pct=entry["uptime_pct"],
                jobs_24h=entry["jobs_24h"],
                volume_24h_lamports=entry["volume_24h_lamports"],
            )
            seeded.append(await service.upsert(relayer))
            typer.echo(f"  upsert {relayer.relayer_id} ({relayer.name}) pubkey={pubkey}")

    return seeded


@app.command()
def main(
    with_demo: bool = typer.Option(
        True,
        "--with-demo/--no-with-demo",
        help="Also upsert the six demo relayers visible in the frontend.",
    ),
) -> None:
    """Seed ``db.relayers`` with this node + (optionally) demo entries."""

    logging.basicConfig(level=settings.log_level, format="%(message)s")
    typer.echo("Seeding db.relayers ...")

    try:
        seeded = asyncio.run(_seed(with_demo=with_demo))
    except BagsVaultError as exc:
        typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
        if exc.details:
            typer.secho(repr(exc.details), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"\nDone. Seeded {len(seeded)} relayer(s).")


if __name__ == "__main__":
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI safety net
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        sys.exit(2)
