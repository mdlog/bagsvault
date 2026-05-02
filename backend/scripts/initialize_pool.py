"""Operator CLI: bootstrap a BagsVault pool by calling the on-chain
``initialize(denomination)`` instruction.

After ``anchor deploy`` puts the program on devnet, exactly one pool per
``token_mint`` must be initialized before any deposit will succeed. This
script wraps that one-shot operation. It is intentionally idempotent at
the cluster level: the on-chain ``init`` constraint causes a duplicate
call to fail with an Anchor error rather than silently overwriting state.

Usage::

    python -m scripts.initialize_pool --denomination 1000000000
    python -m scripts.initialize_pool --denomination 1000000000 --token-mint <mint>
    python -m scripts.initialize_pool --denomination 1000000000 \\
        --cluster mainnet-beta --i-know-what-i-am-doing

Steps:

1. Load settings; refuse mainnet without the explicit override flag.
2. Resolve the token-mint pubkey ("SOL" sentinel = system program ID
   ``11111111111111111111111111111111``).
3. Derive the ``[b"merkle_tree", token_mint]`` PDA — the program reads
   exactly this PDA to find the pool state.
4. Build the Anchor ``initialize`` instruction (sighash =
   ``sha256("global:initialize")[..8]`` + Borsh-encoded ``denomination``).
5. Sign with the relayer keypair (acts as ``authority`` here — for
   production the operator should rotate authority via the admin ix).
6. Simulate via ``simulateTransaction``; abort if it errors.
7. Broadcast via ``sendTransaction`` and pretty-print the resulting PDA
   + signature.

This script is only safe on devnet for hackathon purposes. On mainnet
the authority should be a multisig (Squads, etc.) — the architecture
doc covers the rotation path.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import sys
from typing import Any

import typer
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from app.clients.solana_rpc import SolanaRpcClient
from app.clients.solana_signer import SolanaSignerClient
from app.config import settings
from app.exceptions import BagsVaultError, ServiceUnavailableError, UpstreamError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anchor sighash + layout helpers
# ---------------------------------------------------------------------------
# Anchor instruction discriminator = first 8 bytes of
# ``sha256("global:<ix_name>")``.
INITIALIZE_SIGHASH = hashlib.sha256(b"global:initialize").digest()[:8]

# Sentinel used in the rest of the codebase to mean "this pool is
# native-SOL, not an SPL mint".
SOL_TOKEN_SENTINEL = "SOL"
# System program ID — BagsVault uses this as the token_mint for native
# SOL pools. See programs/bagsvault/src/state.rs.
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# PDA seeds — must mirror programs/bagsvault/src/state.rs::SEED_PREFIX.
MERKLE_TREE_SEED = b"merkle_tree"


app = typer.Typer(add_completion=False, no_args_is_help=False)


def _resolve_token_mint(token_mint: str) -> Pubkey:
    """Translate ``"SOL"`` to the system program ID and parse base58."""

    if token_mint == SOL_TOKEN_SENTINEL or not token_mint:
        return Pubkey.from_string(SYSTEM_PROGRAM_ID)
    try:
        return Pubkey.from_string(token_mint)
    except Exception as exc:  # noqa: BLE001 — surface as CLI error
        raise typer.BadParameter(
            f"--token-mint must be 'SOL' or a base58 pubkey: {exc}"
        ) from exc


def _derive_tree_state_pda(program_id: Pubkey, token_mint: Pubkey) -> tuple[Pubkey, int]:
    """Derive the canonical ``[b"merkle_tree", token_mint]`` pool PDA."""

    pda, bump = Pubkey.find_program_address(
        [MERKLE_TREE_SEED, bytes(token_mint)],
        program_id,
    )
    return pda, bump


def _build_initialize_ix(
    *,
    program_id: Pubkey,
    authority: Pubkey,
    token_mint: Pubkey,
    tree_state: Pubkey,
    denomination: int,
) -> Instruction:
    """Build the Anchor ``initialize`` instruction.

    Account order matches ``Initialize<'info>`` in
    ``programs/bagsvault/src/instructions/initialize.rs``:

    0. authority (signer, writable) — pays rent for the new tree_state.
    1. token_mint (read-only) — used as a PDA seed; we never deref it.
    2. tree_state PDA (init, writable) — the pool state account.
    3. system_program (read-only) — required by the ``init`` constraint.

    Borsh args: ``denomination: u64`` (little-endian).
    """

    data = bytearray()
    data += INITIALIZE_SIGHASH
    data += int(denomination).to_bytes(8, "little")

    accounts = [
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=token_mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=tree_state, is_signer=False, is_writable=True),
        AccountMeta(pubkey=Pubkey.from_string(SYSTEM_PROGRAM_ID), is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=bytes(data))


def _coerce_blockhash(raw: Any) -> str:
    """Accept either a raw blockhash string or the modern dict envelope."""

    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        value = raw.get("blockhash")
        if isinstance(value, str):
            return value
    raise UpstreamError(
        "Solana RPC returned an unexpected blockhash payload.",
        details={"type": type(raw).__name__},
    )


async def _run(
    *,
    denomination: int,
    token_mint_arg: str,
) -> dict[str, Any]:
    """Build, sign, broadcast the initialize ix. Returns the result dict."""

    if not settings.bagsvault_program_id:
        raise ServiceUnavailableError(
            "BAGSVAULT_PROGRAM_ID is not configured.",
            details={"hint": "Set it in backend/.env after `anchor deploy`."},
        )

    program_id = Pubkey.from_string(settings.bagsvault_program_id)
    token_mint = _resolve_token_mint(token_mint_arg)

    signer = SolanaSignerClient()
    authority = signer.pubkey_obj()

    tree_state, bump = _derive_tree_state_pda(program_id, token_mint)
    typer.echo(f"  program_id     {program_id}")
    typer.echo(f"  authority      {authority}")
    typer.echo(f"  token_mint     {token_mint}  ({token_mint_arg})")
    typer.echo(f"  tree_state PDA {tree_state} (bump={bump})")
    typer.echo(f"  denomination   {denomination} lamports")

    ix = _build_initialize_ix(
        program_id=program_id,
        authority=authority,
        token_mint=token_mint,
        tree_state=tree_state,
        denomination=denomination,
    )

    rpc = SolanaRpcClient()
    try:
        blockhash_payload = await rpc.get_recent_blockhash()
    except BagsVaultError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError(
            "Failed to fetch recent blockhash from Solana RPC.",
            details={"error": str(exc)},
        ) from exc
    recent_blockhash = _coerce_blockhash(blockhash_payload)

    signed = signer.build_and_sign(
        instructions=[ix],
        recent_blockhash=recent_blockhash,
        payer=authority,
    )
    signed_b64 = base64.b64encode(signed).decode("ascii")

    try:
        signature = await rpc.send_transaction(signed_b64, skip_preflight=False)
    except BagsVaultError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError(
            "Solana RPC rejected the initialize transaction.",
            details={"error": str(exc)},
        ) from exc
    finally:
        await rpc.aclose()

    return {
        "tree_state_pda": str(tree_state),
        "tree_state_bump": bump,
        "signature": signature,
        "program_id": str(program_id),
        "authority": str(authority),
        "token_mint": str(token_mint),
        "denomination": denomination,
    }


@app.command()
def main(
    denomination: int = typer.Option(
        ...,
        "--denomination",
        help="Fixed pool denomination in lamports (or token base units).",
        min=1,
    ),
    token_mint: str = typer.Option(
        SOL_TOKEN_SENTINEL,
        "--token-mint",
        help="Base58 SPL mint, or 'SOL' for the native pool (system program ID).",
    ),
    cluster: str = typer.Option(
        None,
        "--cluster",
        help="Override SOLANA_CLUSTER for safety check (devnet|testnet|mainnet-beta).",
    ),
    i_know_what_i_am_doing: bool = typer.Option(
        False,
        "--i-know-what-i-am-doing",
        help="Required to run against mainnet-beta.",
    ),
) -> None:
    """Bootstrap a BagsVault pool with the given fixed denomination."""

    logging.basicConfig(level=settings.log_level, format="%(message)s")

    effective_cluster = cluster or settings.solana_cluster
    if effective_cluster == "mainnet-beta" and not i_know_what_i_am_doing:
        typer.secho(
            "Refusing to initialize on mainnet-beta without --i-know-what-i-am-doing.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    typer.echo(f"Initializing BagsVault pool on cluster={effective_cluster} ...")

    try:
        result = asyncio.run(_run(denomination=denomination, token_mint_arg=token_mint))
    except BagsVaultError as exc:
        typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
        if exc.details:
            typer.secho(json.dumps(exc.details, indent=2), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("\n=== Pool initialized ===")
    typer.echo(json.dumps(result, indent=2))
    typer.echo("\nNext steps:")
    typer.echo("  1. Wait for confirmation (use scripts/airdrop_relayer.py to fund the relayer if needed).")
    typer.echo(f"  2. Verify on-chain: solana confirm -v {result['signature']}")
    typer.echo("  3. Try a deposit via POST /api/deposits/build.")


if __name__ == "__main__":
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI safety net
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        sys.exit(3)
