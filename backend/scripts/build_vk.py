"""Operator CLI: drive the BagsVault trusted-setup ceremony pipeline.

Workflow::

    python -m scripts.build_vk compile     # nargo compile
    python -m scripts.build_vk setup       # bb write_vk -> ./target/vk
    python -m scripts.build_vk convert     # vk -> programs/bagsvault/src/verifier_vk.rs
    python -m scripts.build_vk all         # compile + setup + convert

The ``all`` subcommand is what an operator runs on a build machine that
has both ``nargo`` and ``bb`` (Barretenberg) installed. The convert step
is pure Python and can run anywhere — it parses the binary verifying
key blob plus its companion ``vk_fields.json`` and emits a Rust file
``programs/bagsvault/src/verifier_vk.rs`` with literal ``pub const``
byte arrays.

Endianness convention
---------------------
``groth16-solana 0.0.3`` consumes G1 elements as 64 bytes
``[x_be ‖ y_be]`` and G2 elements as 128 bytes ``[c1_x ‖ c0_x ‖ c1_y ‖
c0_y]`` per the Light Protocol parser
(``parse_vk_to_rust.js`` in the crate). Snarkjs / circom output Fp2
coordinates in ``[c0, c1]`` order; we swap them. ``bb``'s
``vk_fields.json`` writes field elements in the same little-endian
``BigInteger`` form that the JS reference parser uses, so we replicate
its ``leInt2Buff(...).reverse()`` transform exactly. See the inline
``_encode_g1`` / ``_encode_g2`` helpers for the byte order we land on.

Trusted-setup safety
--------------------
The verifying key derived from a single-machine ceremony embeds the
"toxic waste" tau on that machine. For production, run a multi-party
ceremony (see ``circuits/bagsvault_withdraw/README.md``). This script
is the automation around the ceremony output — it does **not** make a
single-machine setup safe.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import typer

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Defaults: resolved relative to the repository root so the CLI works
# whether invoked from `backend/` or from a CI machine that mounts the
# whole tree somewhere else (configurable via --ceremony-dir / --repo-root).
# ----------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_CIRCUIT_DIR = REPO_ROOT / "circuits" / "bagsvault_withdraw"
DEFAULT_VERIFIER_VK_PATH = (
    REPO_ROOT / "programs" / "bagsvault" / "src" / "verifier_vk.rs"
)

NARGO_INSTALL_HINT = (
    "nargo not found on PATH. Install Noir + nargo from "
    "https://noir-lang.org/docs/getting_started/installation"
)
BB_INSTALL_HINT = (
    "bb not found on PATH. Install Barretenberg following "
    "https://github.com/AztecProtocol/aztec-packages/tree/master/barretenberg/cpp"
)

NUM_PUBLIC_INPUTS = 5  # mirrors verifier_vk::NUM_PUBLIC_INPUTS

app = typer.Typer(add_completion=False, no_args_is_help=True)


# ----------------------------------------------------------------------
# Subprocess helpers
# ----------------------------------------------------------------------
def _which_or_fail(binary: str, hint: str) -> str:
    """Resolve ``binary`` on PATH or raise a helpful CLI error."""

    found = shutil.which(binary)
    if not found:
        raise typer.BadParameter(hint)
    return found


def _run(cmd: list[str], cwd: Path) -> None:
    """Run ``cmd`` in ``cwd``. On non-zero exit, print last 2 KB of output."""

    typer.echo(f"  $ {' '.join(cmd)}  (cwd={cwd})")
    proc = subprocess.run(  # noqa: S603 — operator-supplied tool paths
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        tail_stdout = proc.stdout.decode("utf-8", errors="replace")[-2048:]
        tail_stderr = proc.stderr.decode("utf-8", errors="replace")[-2048:]
        typer.secho(
            f"  command failed (exit={proc.returncode})",
            fg=typer.colors.RED,
            err=True,
        )
        if tail_stdout:
            typer.secho(f"  --- stdout (tail) ---\n{tail_stdout}", err=True)
        if tail_stderr:
            typer.secho(f"  --- stderr (tail) ---\n{tail_stderr}", err=True)
        raise typer.Exit(code=proc.returncode or 1)


def _resolve_circuit_dir(ceremony_dir: Path | None) -> Path:
    return Path(ceremony_dir).resolve() if ceremony_dir else DEFAULT_CIRCUIT_DIR


# ----------------------------------------------------------------------
# Field-element encoding (BN254)
# ----------------------------------------------------------------------
FIELD_BYTES = 32


def _int_to_be32(value: int) -> bytes:
    """Encode a non-negative integer as a 32-byte big-endian BN254 element."""

    if value < 0:
        raise ValueError(f"VK field element must be non-negative, got {value}")
    if value.bit_length() > 256:
        raise ValueError(
            f"VK field element does not fit in 32 bytes (bit_length={value.bit_length()})."
        )
    return value.to_bytes(FIELD_BYTES, "big")


def _encode_g1(coords: list) -> bytes:
    """Encode a G1 point (x, y) as 64 bytes ``[x_be ‖ y_be]``.

    Mirrors ``vk_alpha_1`` / IC handling in ``parse_vk_to_rust.js``:
    ``leInt2Buff(...).reverse()`` produces big-endian per-coordinate.
    """

    if len(coords) < 2:
        raise ValueError(f"G1 point needs at least 2 coordinates, got {len(coords)}")
    x_int, y_int = int(coords[0]), int(coords[1])
    return _int_to_be32(x_int) + _int_to_be32(y_int)


def _encode_g2(coords: list) -> bytes:
    """Encode a G2 point as 128 bytes per the Light Protocol convention.

    Snarkjs writes ``[[c0_x, c1_x], [c0_y, c1_y], [1, 0]]``. The Light
    Protocol parser ``parse_vk_to_rust.js`` concatenates the two limbs of
    each Fp2 coordinate **then reverses the whole 64-byte slice**, which
    swaps both the limb order (c0/c1) and the byte endianness within
    each limb. We replicate that here so the bytes are interpreted
    correctly by ``alt_bn128_pairing`` on chain.

    Output layout: ``[c1_x_be (32) ‖ c0_x_be (32) ‖ c1_y_be (32) ‖ c0_y_be (32)]``.
    """

    if len(coords) < 2:
        raise ValueError(f"G2 point needs at least 2 Fp2 coordinates, got {len(coords)}")
    x_pair, y_pair = coords[0], coords[1]
    if len(x_pair) < 2 or len(y_pair) < 2:
        raise ValueError("G2 Fp2 coordinates must each have 2 limbs (c0, c1)")

    x_c0, x_c1 = int(x_pair[0]), int(x_pair[1])
    y_c0, y_c1 = int(y_pair[0]), int(y_pair[1])

    # Swap the c0/c1 ordering to match the on-chain consumer.
    return (
        _int_to_be32(x_c1)
        + _int_to_be32(x_c0)
        + _int_to_be32(y_c1)
        + _int_to_be32(y_c0)
    )


# ----------------------------------------------------------------------
# VK parsing
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ParsedVk:
    alpha_g1: bytes
    beta_g2: bytes
    gamma_g2: bytes
    delta_g2: bytes
    ic: list[bytes]

    def public_input_count(self) -> int:
        return len(self.ic) - 1


_REQUIRED_KEYS = {"vk_alpha_1", "vk_beta_2", "vk_gamma_2", "vk_delta_2", "IC"}


def _load_vk_fields_json(path: Path) -> dict:
    """Load ``vk_fields.json`` (or any equivalent JSON the ceremony wrote)."""

    if not path.exists():
        raise typer.BadParameter(
            f"VK JSON not found at {path}. Did you run `bb write_vk` first?"
        )
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"VK JSON at {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise typer.BadParameter(
            f"VK JSON at {path} must be a top-level object, got {type(data).__name__}."
        )
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise typer.BadParameter(
            f"VK JSON at {path} is missing required fields: {sorted(missing)}. "
            "Expected snarkjs/bb-style schema with vk_alpha_1, vk_beta_2, "
            "vk_gamma_2, vk_delta_2, IC."
        )
    return data


def _parse_vk(vk_json: dict) -> ParsedVk:
    """Convert snarkjs-style VK fields into wire-format byte arrays."""

    try:
        alpha_g1 = _encode_g1(vk_json["vk_alpha_1"])
        beta_g2 = _encode_g2(vk_json["vk_beta_2"])
        gamma_g2 = _encode_g2(vk_json["vk_gamma_2"])
        delta_g2 = _encode_g2(vk_json["vk_delta_2"])
        ic_raw = vk_json["IC"]
        if not isinstance(ic_raw, list) or not ic_raw:
            raise typer.BadParameter("VK 'IC' must be a non-empty list of G1 points.")
        ic = [_encode_g1(point) for point in ic_raw]
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(f"Malformed VK JSON: {exc}") from exc

    expected_ic_len = NUM_PUBLIC_INPUTS + 1
    if len(ic) != expected_ic_len:
        raise typer.BadParameter(
            f"VK has {len(ic)} IC entries but the circuit declares "
            f"NUM_PUBLIC_INPUTS={NUM_PUBLIC_INPUTS} (expected IC length "
            f"{expected_ic_len}). The circuit and VK are out of sync — "
            "regenerate the VK from the current circuit."
        )

    return ParsedVk(
        alpha_g1=alpha_g1,
        beta_g2=beta_g2,
        gamma_g2=gamma_g2,
        delta_g2=delta_g2,
        ic=ic,
    )


# ----------------------------------------------------------------------
# Rust source emission
# ----------------------------------------------------------------------
GENERATED_HEADER = (
    "//! GENERATED — DO NOT EDIT BY HAND.\n"
    "//!\n"
    "//! Run `python backend/scripts/build_vk.py all` after changing the\n"
    "//! circuit (`circuits/bagsvault_withdraw/src/main.nr`) to regenerate\n"
    "//! these constants from a fresh trusted-setup ceremony.\n"
    "//!\n"
    "//! See `circuits/bagsvault_withdraw/README.md` for the operator runbook\n"
    "//! and the toxic-waste warning.\n"
    "//!\n"
    "//! Byte layout (matches `groth16-solana 0.0.3`'s `Groth16Verifyingkey`):\n"
    "//!   * `vk_alpha_g1`  — BN254 G1 element, 64 bytes (compressed BE: x ‖ y).\n"
    "//!   * `vk_beta_g2`   — BN254 G2 element, 128 bytes. Light Protocol\n"
    "//!     convention: `[c1_x ‖ c0_x ‖ c1_y ‖ c0_y]` (Fp2 limb order swapped\n"
    "//!     vs. snarkjs JSON). The reference parser is\n"
    "//!     `groth16-solana/parse_vk_to_rust.js` — `build_vk.py convert`\n"
    "//!     mirrors that exact transformation.\n"
    "//!   * `vk_gamma_g2`  — same encoding as `vk_beta_g2`.\n"
    "//!   * `vk_delta_g2`  — same encoding as `vk_beta_g2`.\n"
    "//!   * `vk_ic[i]`     — G1 element, 64 bytes; one entry per public\n"
    "//!     input plus one for the constant term, so\n"
    "//!     `VK_IC.len() == NUM_PUBLIC_INPUTS + 1`.\n"
)


def _format_byte_array(name: str, raw: bytes, length: int) -> str:
    """Emit ``pub const NAME: [u8; LEN] = [..];`` with one byte per item."""

    if len(raw) != length:
        raise ValueError(f"{name}: expected {length} bytes, got {len(raw)}")
    body = ", ".join(str(b) for b in raw)
    wrapped = textwrap.fill(
        body,
        width=92,
        initial_indent="    ",
        subsequent_indent="    ",
        break_long_words=False,
        break_on_hyphens=False,
    )
    return f"pub const {name}: [u8; {length}] = [\n{wrapped}\n];"


def _format_vk_ic(name: str, ic: list[bytes]) -> str:
    rows: list[str] = []
    for entry in ic:
        if len(entry) != 64:
            raise ValueError(f"{name}: IC entry must be 64 bytes, got {len(entry)}")
        body = ", ".join(str(b) for b in entry)
        wrapped = textwrap.fill(
            body,
            width=88,
            initial_indent="        ",
            subsequent_indent="        ",
            break_long_words=False,
            break_on_hyphens=False,
        )
        rows.append("    [\n" + wrapped + "\n    ],")
    body = "\n".join(rows)
    return (
        f"pub const {name}: [[u8; 64]; NUM_PUBLIC_INPUTS + 1] = [\n{body}\n];"
    )


def _render_verifier_vk(parsed: ParsedVk) -> str:
    """Render the full ``verifier_vk.rs`` source from a parsed VK."""

    parts = [
        GENERATED_HEADER,
        "",
        "/// Number of public inputs the circuit exposes. Mirrored in",
        "/// `verifier.rs` so the Rust unit test there can detect a circuit",
        "/// edit that drifts away from the regenerated VK.",
        f"pub const NUM_PUBLIC_INPUTS: usize = {NUM_PUBLIC_INPUTS};",
        "",
        "/// `vk_alpha_g1` (G1, 64 bytes BE-compressed).",
        _format_byte_array("VK_ALPHA_G1", parsed.alpha_g1, 64),
        "",
        "/// `vk_beta_g2` (G2, 128 bytes; see module-level note on Fp2 swap).",
        _format_byte_array("VK_BETA_G2", parsed.beta_g2, 128),
        "",
        "/// `vk_gamma_g2` (G2, 128 bytes; see module-level note on Fp2 swap).",
        _format_byte_array("VK_GAMMA_G2", parsed.gamma_g2, 128),
        "",
        "/// `vk_delta_g2` (G2, 128 bytes; see module-level note on Fp2 swap).",
        _format_byte_array("VK_DELTA_G2", parsed.delta_g2, 128),
        "",
        "/// `vk_ic` table. Length must be `NUM_PUBLIC_INPUTS + 1`; this",
        "/// invariant is asserted by a unit test in `verifier.rs`.",
        _format_vk_ic("VK_IC", parsed.ic),
        "",
    ]
    return "\n".join(parts)


# ----------------------------------------------------------------------
# Subcommands
# ----------------------------------------------------------------------
@app.command()
def compile(  # noqa: A001 — typer subcommand name
    ceremony_dir: Path = typer.Option(
        None,
        "--ceremony-dir",
        help="Override the circuit directory (default: <repo>/circuits/bagsvault_withdraw).",
    ),
) -> None:
    """Run ``nargo compile`` to produce ACIR + circuit JSON."""

    circuit_dir = _resolve_circuit_dir(ceremony_dir)
    if not circuit_dir.exists():
        raise typer.BadParameter(f"Circuit directory does not exist: {circuit_dir}")
    nargo = _which_or_fail("nargo", NARGO_INSTALL_HINT)

    typer.echo(f">>> compile  ({circuit_dir})")
    _run([nargo, "compile"], cwd=circuit_dir)
    typer.secho("  compile OK", fg=typer.colors.GREEN)


@app.command()
def setup(
    ceremony_dir: Path = typer.Option(
        None,
        "--ceremony-dir",
        help="Override the circuit directory (default: <repo>/circuits/bagsvault_withdraw).",
    ),
) -> None:
    """Run ``bb write_vk`` to emit ``./target/vk`` and ``./target/vk_fields.json``."""

    circuit_dir = _resolve_circuit_dir(ceremony_dir)
    bb = _which_or_fail("bb", BB_INSTALL_HINT)
    target = circuit_dir / "target"
    bytecode = target / "bagsvault_withdraw.json"
    if not bytecode.exists():
        raise typer.BadParameter(
            f"Circuit bytecode missing at {bytecode}. Run `compile` first."
        )

    typer.echo(f">>> setup  ({circuit_dir})")
    # ``bb`` writes the binary VK to ``-o``; modern releases also drop a
    # JSON sibling next to it (``vk_fields.json``) when invoked with
    # ``--output_format`` or by default depending on version. We trust
    # the operator's bb to produce both; ``convert`` will validate.
    _run(
        [
            bb,
            "write_vk",
            "-b",
            str(bytecode),
            "-o",
            str(target / "vk"),
        ],
        cwd=circuit_dir,
    )
    typer.secho("  setup OK", fg=typer.colors.GREEN)


@app.command()
def convert(
    ceremony_dir: Path = typer.Option(
        None,
        "--ceremony-dir",
        help="Override the circuit directory (default: <repo>/circuits/bagsvault_withdraw).",
    ),
    vk_fields_json: Path = typer.Option(
        None,
        "--vk-fields-json",
        help="Path to the snarkjs-style verifying-key JSON (default: <ceremony>/target/vk_fields.json).",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        help="Where to write verifier_vk.rs (default: programs/bagsvault/src/verifier_vk.rs).",
    ),
) -> None:
    """Convert the ceremony's verifying key into ``programs/bagsvault/src/verifier_vk.rs``."""

    circuit_dir = _resolve_circuit_dir(ceremony_dir)
    json_path = (
        Path(vk_fields_json).resolve()
        if vk_fields_json
        else circuit_dir / "target" / "vk_fields.json"
    )
    out_path = Path(output).resolve() if output else DEFAULT_VERIFIER_VK_PATH

    typer.echo(f">>> convert  (vk-json={json_path})")
    vk_json = _load_vk_fields_json(json_path)
    parsed = _parse_vk(vk_json)
    rendered = _render_verifier_vk(parsed)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    typer.secho(
        f"  wrote {out_path}  ({len(parsed.ic)} IC entries, "
        f"public_inputs={parsed.public_input_count()})",
        fg=typer.colors.GREEN,
    )


@app.command()
def all(  # noqa: A003 — typer subcommand name
    ceremony_dir: Path = typer.Option(
        None,
        "--ceremony-dir",
        help="Override the circuit directory (default: <repo>/circuits/bagsvault_withdraw).",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        help="Where to write verifier_vk.rs (default: programs/bagsvault/src/verifier_vk.rs).",
    ),
) -> None:
    """Run compile -> setup -> convert end-to-end."""

    compile(ceremony_dir=ceremony_dir)
    setup(ceremony_dir=ceremony_dir)
    convert(ceremony_dir=ceremony_dir, vk_fields_json=None, output=output)
    typer.secho("\nceremony pipeline OK", fg=typer.colors.GREEN, bold=True)


def _main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(message)s")
    app()


if __name__ == "__main__":
    try:
        _main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI safety net
        typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)
        sys.exit(2)
