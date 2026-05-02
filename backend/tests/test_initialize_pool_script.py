"""Light tests for the ``scripts.initialize_pool`` typer CLI.

We don't shell out — using ``typer.testing.CliRunner`` avoids any real
network / signing while still exercising the argument parsing + safety
guards. Two cases that matter for the hackathon demo:

1. The module imports cleanly and registers a single command — protects
   against future "I forgot to commit a constant" regressions.
2. Running against ``--cluster mainnet-beta`` without the explicit
   override flag exits non-zero. This is the only behaviour stopping
   somebody from accidentally redeploying a pool to mainnet during a
   fast hackathon iteration.
"""

from __future__ import annotations

import hashlib

from typer.testing import CliRunner

from scripts import initialize_pool


def test_module_imports_and_exposes_typer_app() -> None:
    """Smoke test — catches missing imports / syntax issues at CI time."""

    assert hasattr(initialize_pool, "app")
    # The expected sighash is the first 8 bytes of sha256("global:initialize").
    expected = hashlib.sha256(b"global:initialize").digest()[:8]
    assert initialize_pool.INITIALIZE_SIGHASH == expected


def test_pda_helpers_use_documented_seeds() -> None:
    """Pin the PDA seed string — must mirror programs/bagsvault/state.rs."""

    assert initialize_pool.MERKLE_TREE_SEED == b"merkle_tree"
    assert initialize_pool.SYSTEM_PROGRAM_ID == "11111111111111111111111111111111"


def test_cli_rejects_mainnet_without_override_flag() -> None:
    """``--cluster mainnet-beta`` alone must exit non-zero."""

    runner = CliRunner()
    result = runner.invoke(
        initialize_pool.app,
        ["--denomination", "1000000000", "--cluster", "mainnet-beta"],
    )
    assert result.exit_code != 0
    # The error banner is printed to stderr — Typer merges it into the
    # CliRunner output unless mix_stderr=False is passed.
    assert "mainnet-beta" in result.stdout or "mainnet-beta" in (result.stderr or "")


def test_cli_help_invocation_succeeds() -> None:
    """Sanity: ``--help`` exits cleanly and mentions the program name.

    We deliberately avoid grepping individual flag names because Typer
    truncates help output at terminal width during testing — the exit
    code + a presence-of-usage check is enough to catch a broken CLI.
    """

    runner = CliRunner()
    result = runner.invoke(initialize_pool.app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
