"""ZK proof generator endpoints.

Two surfaces are exposed:

* ``POST /api/proofs/commitment`` — given a (nullifier, secret, amount)
  triple, returns the Poseidon commitment leaf the deposit transaction
  must publish. Clients call this *before* sending the deposit tx so the
  deposit ix carries the canonical commitment.
* ``POST /api/proofs/withdraw`` — given the full witness, runs the Noir
  toolchain and returns a 256-byte Groth16 proof + the public-input
  vector. The :class:`WithdrawalService` posts this proof to the
  on-chain verifier.

The proof generator is intentionally separated from the relay endpoint
so that:

* clients can produce proofs locally (browser-side WASM) without round-
  tripping through the backend, and
* operators can scale proof generation horizontally (CPU-bound) without
  touching the latency-sensitive relay path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.zk_proof_service import (
    WithdrawProofInput,
    ZkProofService,
    get_zk_proof_service,
)

router = APIRouter(prefix="/proofs", tags=["proofs"])


class CommitmentRequest(BaseModel):
    """Inputs to derive the deposit commitment leaf."""

    nullifier: str = Field(..., description="Hex-encoded random nullifier (≤ 32 bytes).")
    secret: str = Field(..., description="Hex-encoded random secret (≤ 32 bytes).")
    amount: int = Field(..., ge=0, description="Deposit amount in smallest units.")


class CommitmentResponse(BaseModel):
    commitment_hex: str
    nullifier_hex: str
    secret_hex: str


class WithdrawProofRequest(BaseModel):
    """Full witness needed to produce a withdraw proof."""

    nullifier: str = Field(..., description="Hex-encoded nullifier preimage.")
    secret: str = Field(..., description="Hex-encoded secret preimage.")
    amount: int = Field(..., ge=0, description="Pool denomination (smallest units).")
    leaf_index: int = Field(..., ge=0, description="Position of the commitment in the tree.")
    merkle_path: list[str] = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Sibling hashes from leaf to root (hex strings).",
    )
    is_left: list[int] = Field(
        ...,
        min_length=1,
        max_length=32,
        description="One bit per level (0 or 1) — current node side at that level.",
    )
    recipient: str = Field(..., description="Recipient pubkey as base58 OR 32-byte hex.")
    relayer: str = Field(..., description="Relayer pubkey as base58 OR 32-byte hex.")
    fee_bps: int = Field(
        ...,
        ge=0,
        le=10_000,
        description=(
            "Pool's advertised relayer cut in basis points; bound into "
            "the proof at public-input index 5."
        ),
    )


class WithdrawProofResponse(BaseModel):
    proof_hex: str
    root_hex: str
    nullifier_hash_hex: str
    commitment_hex: str
    public_inputs_hex: list[str]


def _hex_to_int(value: str, *, label: str) -> int:
    raw = value.strip()
    if raw.startswith("0x") or raw.startswith("0X"):
        raw = raw[2:]
    if not raw:
        raise ValueError(f"{label} is empty")
    try:
        return int(raw, 16)
    except ValueError as exc:
        raise ValueError(f"{label} is not valid hex") from exc


def _hex_to_pubkey_bytes(value: str, *, label: str) -> bytes:
    """Accept either a base58 Solana pubkey or a 32-byte hex string."""

    raw = value.strip()
    if raw.startswith("0x") or raw.startswith("0X"):
        raw = raw[2:]
    # Try hex first.
    try:
        candidate = bytes.fromhex(raw)
        if len(candidate) == 32:
            return candidate
    except ValueError:
        pass
    # Fall back to base58.
    try:
        from solders.pubkey import Pubkey

        return bytes(Pubkey.from_string(value.strip()))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{label} must be base58 pubkey or 32-byte hex") from exc


@router.post("/commitment", response_model=CommitmentResponse)
async def derive_commitment(
    payload: CommitmentRequest,
    service: ZkProofService = Depends(get_zk_proof_service),
) -> CommitmentResponse:
    """Compute the Poseidon commitment a deposit must publish."""

    nullifier = _hex_to_int(payload.nullifier, label="nullifier")
    secret = _hex_to_int(payload.secret, label="secret")
    commitment = service.commitment(nullifier, secret, payload.amount)
    return CommitmentResponse(
        commitment_hex="0x" + commitment.to_bytes(32, "big").hex(),
        nullifier_hex="0x" + (nullifier % (1 << 256)).to_bytes(32, "big").hex(),
        secret_hex="0x" + (secret % (1 << 256)).to_bytes(32, "big").hex(),
    )


@router.post("/withdraw", response_model=WithdrawProofResponse)
async def generate_withdraw_proof(
    payload: WithdrawProofRequest,
    service: ZkProofService = Depends(get_zk_proof_service),
) -> WithdrawProofResponse:
    """Run the Noir + bb pipeline and return a Groth16 proof."""

    if len(payload.merkle_path) != len(payload.is_left):
        raise ValueError("merkle_path and is_left must have equal length")

    inp = WithdrawProofInput(
        nullifier=_hex_to_int(payload.nullifier, label="nullifier"),
        secret=_hex_to_int(payload.secret, label="secret"),
        amount=payload.amount,
        leaf_index=payload.leaf_index,
        merkle_path=[_hex_to_int(v, label="merkle_path entry") for v in payload.merkle_path],
        is_left=[1 if int(b) else 0 for b in payload.is_left],
        recipient_pubkey_bytes=_hex_to_pubkey_bytes(payload.recipient, label="recipient"),
        relayer_pubkey_bytes=_hex_to_pubkey_bytes(payload.relayer, label="relayer"),
        fee_bps=payload.fee_bps,
    )
    result = await service.generate_withdraw_proof(inp)
    return WithdrawProofResponse(
        proof_hex=result.proof_hex,
        root_hex=result.root_hex,
        nullifier_hash_hex=result.nullifier_hash_hex,
        commitment_hex=result.commitment_hex,
        public_inputs_hex=result.public_inputs_hex,
    )


@router.get("/health")
async def proof_health(
    service: ZkProofService = Depends(get_zk_proof_service),
) -> dict[str, Any]:
    """Probe whether the underlying toolchain is available."""

    available = service._toolchain_available()  # noqa: SLF001 — internal probe
    return {
        "toolchain_available": available,
        "stub_mode": service._stub_mode,  # noqa: SLF001
        "circuit_dir": str(service._circuit_dir),  # noqa: SLF001
    }
