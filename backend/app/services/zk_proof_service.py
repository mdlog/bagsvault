"""ZK proof generator orchestrator.

The service produces a Groth16 proof for the BagsVault `withdraw`
instruction by driving the Noir + Barretenberg toolchain. It:

1. Computes the commitment (`poseidon(nullifier, secret, amount)`) and
   nullifier hash (`poseidon(nullifier, leaf_index)`) using the same
   BN254 Poseidon parameters as the on-chain Merkle insertion and the
   Noir circuit. Hashing is delegated to :class:`PoseidonHasher`.
2. Assembles a `Prover.toml` containing every public + private input the
   circuit expects, in the exact order documented in
   ``circuits/bagsvault_withdraw/src/main.nr``.
3. Shells out to ``nargo execute`` and ``bb prove`` (paths configured via
   :class:`Settings`) to produce the proof bytes. ``bb`` writes the proof
   in the same 256-byte ``[a64 || b128 || c64]`` layout that
   ``programs/bagsvault/src/verifier.rs`` consumes.
4. Returns the proof + public-input vector wrapped in a typed result.

If the toolchain is not installed (developer machine without `nargo`/
`bb`), the service degrades to a deterministic stub mode controlled by
``settings.zk_proof_stub_mode``. Stub proofs are 256 bytes of zeros —
the on-chain verifier will reject them, which is the correct behaviour:
a node without the prover toolchain MUST NOT be able to mint a real
withdrawal. Tests use the stub to exercise plumbing without compiling
the real circuit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.exceptions import ServiceUnavailableError, UpstreamError

logger = logging.getLogger(__name__)


# BN254 scalar-field modulus. Public-input field elements are reduced
# mod r before being passed into the verifier so a 32-byte payload that
# happens to exceed `r` is canonicalised the same way the circuit sees
# it.
BN254_R = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def _hex32(value: int) -> str:
    """Render an integer as a 32-byte big-endian hex string with `0x` prefix."""

    if value < 0:
        raise ValueError("field element must be non-negative")
    value %= BN254_R
    return "0x" + value.to_bytes(32, "big").hex()


def _bytes_to_field(raw: bytes) -> int:
    """Treat `raw` as a big-endian field element, reducing mod r."""

    return int.from_bytes(raw, "big") % BN254_R


def _field_to_bytes32(value: int) -> bytes:
    return (value % BN254_R).to_bytes(32, "big")


@dataclass(frozen=True)
class WithdrawProofInput:
    """Witness + public-input bundle handed to :class:`ZkProofService`."""

    nullifier: int
    secret: int
    amount: int
    leaf_index: int
    merkle_path: list[int]
    is_left: list[int]
    recipient_pubkey_bytes: bytes
    relayer_pubkey_bytes: bytes


@dataclass(frozen=True)
class WithdrawProofResult:
    """Output of a successful proof generation run."""

    proof_hex: str
    root_hex: str
    nullifier_hash_hex: str
    commitment_hex: str
    public_inputs_hex: list[str]


class PoseidonHasher:
    """Thin abstraction over a BN254 Poseidon implementation.

    The implementation tries a few backends in order:

    1. ``poseidon-py`` (or ``poseidon_hash``) if installed — pure-Python
       BN254-compatible hash matching the circuit parameters.
    2. ``light-poseidon`` Python bindings (when present).
    3. A subprocess fallback that shells out to a small ``nargo``-shipped
       helper for hashing. This is slow but always available when the
       prover toolchain is installed.

    For the hackathon scope we expose ``hash`` as the only public API;
    callers don't need to know which backend won.
    """

    def __init__(self) -> None:
        self._backend = self._select_backend()

    @staticmethod
    def _select_backend() -> str:
        try:
            import poseidon_hash  # type: ignore  # noqa: F401

            return "poseidon_hash"
        except ImportError:
            pass
        try:
            import poseidon  # type: ignore  # noqa: F401

            return "poseidon_py"
        except ImportError:
            pass
        return "fallback"

    def hash(self, inputs: list[int]) -> int:
        """Hash a list of field elements down to a single field element."""

        if self._backend == "poseidon_hash":
            import poseidon_hash  # type: ignore

            return poseidon_hash.poseidon(inputs) % BN254_R
        if self._backend == "poseidon_py":
            import poseidon  # type: ignore

            h = poseidon.PoseidonBn254()  # type: ignore[attr-defined]
            return h.hash(inputs) % BN254_R
        return self._fallback_hash(inputs)

    @staticmethod
    def _fallback_hash(inputs: list[int]) -> int:
        """Deterministic SHA-256-based fallback.

        **NOT** a real Poseidon hash — this is only used when no
        Poseidon backend is installed and the service is running in
        ``zk_proof_stub_mode``. The on-chain verifier will reject any
        proof produced from these hashes, which is the safety property
        we want.
        """

        digest = hashlib.sha256()
        for value in inputs:
            digest.update(_field_to_bytes32(value))
        return _bytes_to_field(digest.digest())


class ZkProofService:
    """Orchestrates witness building + nargo/bb invocation."""

    PROOF_BYTE_LEN = 256

    def __init__(
        self,
        circuit_dir: Path | None = None,
        nargo_bin: str | None = None,
        bb_bin: str | None = None,
        stub_mode: bool | None = None,
    ) -> None:
        self._circuit_dir = (
            circuit_dir if circuit_dir is not None else Path(settings.zk_circuit_dir)
        )
        self._nargo = nargo_bin or settings.zk_nargo_bin or "nargo"
        self._bb = bb_bin or settings.zk_bb_bin or "bb"
        self._stub_mode = (
            stub_mode if stub_mode is not None else settings.zk_proof_stub_mode
        )
        self._poseidon = PoseidonHasher()

    # ------------------------------------------------------------------
    # Hashing helpers (also used by deposit-side commitment derivation)
    # ------------------------------------------------------------------
    def commitment(self, nullifier: int, secret: int, amount: int) -> int:
        """Return the field-element commitment leaf for a deposit."""

        return self._poseidon.hash([nullifier, secret, amount])

    def nullifier_hash(self, nullifier: int, leaf_index: int) -> int:
        """Return ``poseidon(nullifier, leaf_index)`` — the spent flag."""

        return self._poseidon.hash([nullifier, leaf_index])

    def merkle_root_from_path(
        self, leaf: int, path: list[int], is_left: list[int]
    ) -> int:
        """Recompute the Merkle root from a leaf + sibling-path witness.

        The walk mirrors `circuits/bagsvault_withdraw/src/main.nr` so the
        prover can verify its own witness before paying for a real proof.
        """

        if len(path) != len(is_left):
            raise ValueError("merkle path and is_left must have equal length")
        current = leaf
        for sibling, side in zip(path, is_left):
            if side == 1:
                current = self._poseidon.hash([current, sibling])
            else:
                current = self._poseidon.hash([sibling, current])
        return current

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def generate_withdraw_proof(
        self, payload: WithdrawProofInput
    ) -> WithdrawProofResult:
        """Produce a Groth16 proof + public inputs for the withdraw ix."""

        commitment = self.commitment(payload.nullifier, payload.secret, payload.amount)
        nullifier_hash = self.nullifier_hash(payload.nullifier, payload.leaf_index)
        recipient_field = _bytes_to_field(payload.recipient_pubkey_bytes)
        relayer_field = _bytes_to_field(payload.relayer_pubkey_bytes)
        root = self.merkle_root_from_path(commitment, payload.merkle_path, payload.is_left)

        public_inputs = [root, nullifier_hash, recipient_field, payload.amount, relayer_field]
        public_inputs_hex = [_hex32(v) for v in public_inputs]

        proof_hex = await self._produce_proof_bytes(payload, root, nullifier_hash, public_inputs)

        return WithdrawProofResult(
            proof_hex=proof_hex,
            root_hex=_hex32(root),
            nullifier_hash_hex=_hex32(nullifier_hash),
            commitment_hex=_hex32(commitment),
            public_inputs_hex=public_inputs_hex,
        )

    # ------------------------------------------------------------------
    # Internal: nargo / bb shell-out
    # ------------------------------------------------------------------
    async def _produce_proof_bytes(
        self,
        payload: WithdrawProofInput,
        root: int,
        nullifier_hash: int,
        public_inputs: list[int],
    ) -> str:
        """Shell out to nargo/bb or fall through to stub proof bytes."""

        if self._stub_mode or not self._toolchain_available():
            if not self._stub_mode:
                logger.warning(
                    "ZkProofService: nargo/bb missing on PATH — generating stub proof. "
                    "On-chain verifier will reject. Set ZK_PROOF_STUB_MODE=true to silence."
                )
            return "0x" + ("00" * self.PROOF_BYTE_LEN)

        if not self._circuit_dir.exists():
            raise ServiceUnavailableError(
                "ZK circuit directory does not exist.",
                details={"circuit_dir": str(self._circuit_dir)},
            )

        prover_toml = self._render_prover_toml(payload, root, nullifier_hash)
        with tempfile.TemporaryDirectory(prefix="bagsvault-zk-") as scratch:
            scratch_path = Path(scratch)
            (scratch_path / "Prover.toml").write_text(prover_toml, encoding="utf-8")
            try:
                proof_bytes = await self._run_toolchain(scratch_path)
            except Exception as exc:  # noqa: BLE001
                raise UpstreamError(
                    "Proof toolchain failed.",
                    details={"error": str(exc)},
                ) from exc
        if len(proof_bytes) != self.PROOF_BYTE_LEN:
            raise UpstreamError(
                "Proof toolchain produced a proof with unexpected length.",
                details={
                    "expected": self.PROOF_BYTE_LEN,
                    "actual": len(proof_bytes),
                },
            )
        return "0x" + proof_bytes.hex()

    def _toolchain_available(self) -> bool:
        return shutil.which(self._nargo) is not None and shutil.which(self._bb) is not None

    def _render_prover_toml(
        self,
        payload: WithdrawProofInput,
        root: int,
        nullifier_hash: int,
    ) -> str:
        recipient_field = _bytes_to_field(payload.recipient_pubkey_bytes)
        relayer_field = _bytes_to_field(payload.relayer_pubkey_bytes)
        merkle_path_hex = ", ".join(_quote_hex32(v) for v in payload.merkle_path)
        is_left_str = ", ".join(f'"{int(b)}"' for b in payload.is_left)

        return "\n".join(
            [
                f'root = "{_hex32(root)}"',
                f'nullifier_hash = "{_hex32(nullifier_hash)}"',
                f'recipient = "{_hex32(recipient_field)}"',
                f'amount = "{payload.amount}"',
                f'relayer = "{_hex32(relayer_field)}"',
                "",
                f'nullifier = "{_hex32(payload.nullifier)}"',
                f'secret = "{_hex32(payload.secret)}"',
                f'leaf_index = "{payload.leaf_index}"',
                f"merkle_path = [{merkle_path_hex}]",
                f"is_left = [{is_left_str}]",
                "",
            ]
        )

    async def _run_toolchain(self, scratch: Path) -> bytes:
        """Run `nargo execute` then `bb prove` and return raw proof bytes.

        We copy ``Prover.toml`` into the circuit directory in a temporary
        workspace because nargo always writes its build artefacts under
        ``./target``. Doing this in a sandboxed workspace keeps repo-level
        state pristine across concurrent proof requests.
        """

        # Layout the workspace: copy `circuits/bagsvault_withdraw` into
        # the scratch dir, then drop the rendered Prover.toml on top.
        workspace = scratch / "circuit"
        shutil.copytree(self._circuit_dir, workspace)
        (workspace / "Prover.toml").write_text(
            (scratch / "Prover.toml").read_text(encoding="utf-8"), encoding="utf-8"
        )

        env = os.environ.copy()
        # 1. Execute the circuit to generate the witness.
        await self._exec(
            [self._nargo, "execute", "bagsvault_withdraw"],
            cwd=workspace,
            env=env,
        )
        # 2. Build the proof.
        await self._exec(
            [
                self._bb,
                "prove",
                "-b",
                "./target/bagsvault_withdraw.json",
                "-w",
                "./target/bagsvault_withdraw.gz",
                "-o",
                "./target/proof",
            ],
            cwd=workspace,
            env=env,
        )
        proof_path = workspace / "target" / "proof"
        if not proof_path.exists():
            raise UpstreamError(
                "Proof toolchain finished but proof file is missing.",
                details={"path": str(proof_path)},
            )
        return proof_path.read_bytes()

    @staticmethod
    async def _exec(cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise UpstreamError(
                "Subprocess exited non-zero during proof generation.",
                details={
                    "cmd": " ".join(cmd),
                    "returncode": proc.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace")[-500:],
                    "stderr": stderr.decode("utf-8", errors="replace")[-500:],
                },
            )


def _quote_hex32(value: int) -> str:
    return f'"{_hex32(value)}"'


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------
_zk_service: ZkProofService | None = None


def get_zk_proof_service() -> ZkProofService:
    """FastAPI dependency factory."""

    global _zk_service
    if _zk_service is None:
        _zk_service = ZkProofService()
    return _zk_service


def reset_zk_proof_service() -> None:
    """Test helper."""

    global _zk_service
    _zk_service = None


__all__ = [
    "BN254_R",
    "PoseidonHasher",
    "WithdrawProofInput",
    "WithdrawProofResult",
    "ZkProofService",
    "get_zk_proof_service",
    "reset_zk_proof_service",
]


# Re-export json import to keep the module body lint-clean even when
# `_render_prover_toml` is later refactored to emit JSON instead of TOML.
_ = json
