"""Tests for ``backend/scripts/build_vk.py``.

The CLI only matters at the seams: argument parsing, malformed-input
rejection, and the shape of the Rust source it emits. The actual
``nargo`` / ``bb`` shell-outs are integration concerns and live behind
the operator runbook.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scripts import build_vk


runner = CliRunner()


# ---------------------------------------------------------------------
# CLI surface — subcommands parse and respond to --help
# ---------------------------------------------------------------------
@pytest.mark.parametrize("subcommand", ["compile", "setup", "convert", "all"])
def test_subcommands_expose_help(subcommand: str) -> None:
    result = runner.invoke(build_vk.app, [subcommand, "--help"])
    assert result.exit_code == 0, result.output
    assert "--ceremony-dir" in result.output


def test_top_level_help_lists_every_subcommand() -> None:
    result = runner.invoke(build_vk.app, ["--help"])
    assert result.exit_code == 0, result.output
    for sub in ("compile", "setup", "convert", "all"):
        assert sub in result.output


# ---------------------------------------------------------------------
# `convert` rejects malformed VK JSON
# ---------------------------------------------------------------------
def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_convert_rejects_missing_file(tmp_path: Path) -> None:
    out = tmp_path / "out.rs"
    missing = tmp_path / "does_not_exist.json"
    result = runner.invoke(
        build_vk.app,
        [
            "convert",
            "--ceremony-dir",
            str(tmp_path),
            "--vk-fields-json",
            str(missing),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert "VK JSON not found" in result.output or "does_not_exist" in result.output
    assert not out.exists()


def test_convert_rejects_non_json(tmp_path: Path) -> None:
    bad = tmp_path / "vk.json"
    bad.write_text("this is not json", encoding="utf-8")
    out = tmp_path / "out.rs"
    result = runner.invoke(
        build_vk.app,
        [
            "convert",
            "--ceremony-dir",
            str(tmp_path),
            "--vk-fields-json",
            str(bad),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert "valid JSON" in result.output or "JSON" in result.output


def test_convert_rejects_missing_required_keys(tmp_path: Path) -> None:
    bad = _write(tmp_path / "vk.json", {"vk_alpha_1": []})
    out = tmp_path / "out.rs"
    result = runner.invoke(
        build_vk.app,
        [
            "convert",
            "--ceremony-dir",
            str(tmp_path),
            "--vk-fields-json",
            str(bad),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert "missing required" in result.output.lower() or "required" in result.output.lower()


def test_convert_rejects_wrong_ic_length(tmp_path: Path) -> None:
    """If the circuit declares 5 public inputs the IC table must have 6 entries."""

    payload = {
        "vk_alpha_1": ["1", "2"],
        "vk_beta_2": [["1", "2"], ["3", "4"], ["1", "0"]],
        "vk_gamma_2": [["1", "2"], ["3", "4"], ["1", "0"]],
        "vk_delta_2": [["1", "2"], ["3", "4"], ["1", "0"]],
        # Only 2 IC entries → wrong for 5 public inputs.
        "IC": [["1", "2"], ["3", "4"]],
    }
    bad = _write(tmp_path / "vk.json", payload)
    out = tmp_path / "out.rs"
    result = runner.invoke(
        build_vk.app,
        [
            "convert",
            "--ceremony-dir",
            str(tmp_path),
            "--vk-fields-json",
            str(bad),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert "IC entries" in result.output or "out of sync" in result.output


# ---------------------------------------------------------------------
# Happy path: a synthetic VK round-trips into syntactically-valid Rust
# ---------------------------------------------------------------------
def _synthetic_vk(num_public_inputs: int) -> dict:
    """Build a snarkjs-shaped VK with well-formed integer strings.

    The values themselves are nonsense (the test only cares about shape
    and Rust-formatting), but every element fits in 32 bytes so encoding
    can't blow up.
    """

    g1 = ["123456789", "987654321"]
    g2 = [["1", "2"], ["3", "4"], ["1", "0"]]
    return {
        "vk_alpha_1": g1,
        "vk_beta_2": g2,
        "vk_gamma_2": g2,
        "vk_delta_2": g2,
        "IC": [g1 for _ in range(num_public_inputs + 1)],
    }


def test_convert_emits_well_formed_rust(tmp_path: Path) -> None:
    vk_json = _synthetic_vk(build_vk.NUM_PUBLIC_INPUTS)
    vk_path = _write(tmp_path / "vk.json", vk_json)
    out = tmp_path / "verifier_vk.rs"

    result = runner.invoke(
        build_vk.app,
        [
            "convert",
            "--ceremony-dir",
            str(tmp_path),
            "--vk-fields-json",
            str(vk_path),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()

    text = out.read_text(encoding="utf-8")

    # GENERATED header must be present so a future operator knows not to
    # hand-edit the file.
    assert "GENERATED — DO NOT EDIT BY HAND" in text

    # Each constant must be declared with the exact size groth16-solana
    # expects.
    expected = [
        r"pub const NUM_PUBLIC_INPUTS: usize = 5;",
        r"pub const VK_ALPHA_G1: \[u8; 64\] = \[",
        r"pub const VK_BETA_G2: \[u8; 128\] = \[",
        r"pub const VK_GAMMA_G2: \[u8; 128\] = \[",
        r"pub const VK_DELTA_G2: \[u8; 128\] = \[",
        r"pub const VK_IC: \[\[u8; 64\]; NUM_PUBLIC_INPUTS \+ 1\] = \[",
    ]
    for pattern in expected:
        assert re.search(pattern, text), f"missing pattern: {pattern}\n{text[:500]}"

    # Lightweight Rust-syntax checks:
    # * balanced brackets
    # * each `pub const` block closes with `];`
    assert text.count("[") == text.count("]"), "unbalanced [] in generated Rust"
    assert text.count("{") == text.count("}"), "unbalanced {} in generated Rust"
    assert text.rstrip().endswith("];"), "generated Rust must end with `];`"

    # IC must declare exactly NUM_PUBLIC_INPUTS + 1 entries — count the
    # nested `[\n` array openers inside the VK_IC block.
    ic_block = text.split("pub const VK_IC", 1)[1]
    # Stop at the closing `];` of the VK_IC array.
    ic_end = ic_block.index("\n];")
    ic_body = ic_block[:ic_end]
    inner_arrays = re.findall(r"^\s+\[$", ic_body, flags=re.MULTILINE)
    assert len(inner_arrays) == build_vk.NUM_PUBLIC_INPUTS + 1, (
        f"expected {build_vk.NUM_PUBLIC_INPUTS + 1} IC entries, "
        f"got {len(inner_arrays)}"
    )


# ---------------------------------------------------------------------
# Pure-function unit tests for the encoders. These catch endianness
# regressions before they reach the on-chain verifier.
# ---------------------------------------------------------------------
def test_encode_g1_is_big_endian_per_coord() -> None:
    raw = build_vk._encode_g1(["1", "2"])
    assert len(raw) == 64
    assert raw[:32] == (1).to_bytes(32, "big")
    assert raw[32:] == (2).to_bytes(32, "big")


def test_encode_g2_swaps_fp2_limbs() -> None:
    """Per Light Protocol convention, c0/c1 are swapped vs. snarkjs."""

    raw = build_vk._encode_g2([["10", "20"], ["30", "40"], ["1", "0"]])
    assert len(raw) == 128
    # x_c1 first, then x_c0, then y_c1, then y_c0 — see _encode_g2 docstring.
    assert raw[0:32] == (20).to_bytes(32, "big")
    assert raw[32:64] == (10).to_bytes(32, "big")
    assert raw[64:96] == (40).to_bytes(32, "big")
    assert raw[96:128] == (30).to_bytes(32, "big")


def test_int_to_be32_rejects_oversized_field_elements() -> None:
    too_big = 1 << 256
    with pytest.raises(ValueError):
        build_vk._int_to_be32(too_big)
    with pytest.raises(ValueError):
        build_vk._int_to_be32(-1)
