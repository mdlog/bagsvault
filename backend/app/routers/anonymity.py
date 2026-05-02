"""Anonymity-set + Merkle-root endpoints.

These endpoints power frontend pages that need a quick read of the
``commitments`` count + latest known root, plus the Merkle inclusion
proof needed to construct a withdraw witness. They are intentionally
tolerant: if the BagsVault program ID is not yet configured (no roots
in the cache), they fall back to the all-zeroes empty-tree path rather
than 503ing — the landing/withdraw views must always render.

The merkle-path endpoint is the off-chain piece of the withdraw flow.
The Anchor program owns the source of truth in
``MerkleTreeState.filled_subtrees`` + ``roots``; here we serve a
best-effort path reconstruction by replaying inserted commitments from
``db.commitments``. When the on-chain state is reachable we will
eventually swap that for a direct read of ``filled_subtrees`` (Phase 3).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clients.solana_rpc import SolanaRpcClient, get_solana_rpc_client
from app.config import settings
from app.database import get_db
from app.exceptions import NotFoundError
from app.services.deposit_service import DepositService
from app.services.merkle_indexer import MerkleIndexer

router = APIRouter(tags=["anonymity"])

_FALLBACK_ROOT = "0" * 64
_RECENT_ROOTS_LIMIT = 10
# Tree depth — must match programs/bagsvault/src/state.rs::MERKLE_TREE_DEPTH.
_MERKLE_TREE_DEPTH = 20


def _make_indexer(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> MerkleIndexer:
    return MerkleIndexer(rpc=rpc, db=db)


def _make_deposit_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    rpc: SolanaRpcClient = Depends(get_solana_rpc_client),
) -> DepositService:
    indexer = MerkleIndexer(rpc=rpc, db=db)
    return DepositService(rpc=rpc, db=db, merkle=indexer)


@router.get("/anonymity-set")
async def get_anonymity_set(
    service: DepositService = Depends(_make_deposit_service),
) -> dict[str, Any]:
    """Return ``{count, current_root, updated_at, source}`` for the pool."""

    return await service.get_anonymity_set()


@router.get("/anonymity/state")
async def get_anonymity_state(
    service: DepositService = Depends(_make_deposit_service),
) -> dict[str, Any]:
    """Alias of ``/anonymity-set`` — frontend-friendly path.

    Same payload, just nested under ``/anonymity/...`` to match the
    namespace the frontend Withdraw flow expects.
    """

    return await service.get_anonymity_set()


@router.get("/anonymity/merkle-path")
async def get_merkle_path(
    leaf_index: int = Query(..., ge=0, description="Zero-based leaf index in the tree."),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Return the Merkle inclusion path for ``leaf_index``.

    The response shape:
    ``{leaf_index, depth, siblings: [hex; depth], is_left: [bool; depth],
       source: 'reconstructed' | 'fallback-empty'}``.

    Path reconstruction strategy:

    * Read all commitments up to ``leaf_index`` (inclusive) from
      ``db.commitments``. Replay an incremental Merkle insertion to
      collect the sibling at each level.
    * If the indexer is empty (no commitments cached, e.g. brand-new
      pool) we fall back to the all-zero-sibling path against the
      empty tree. **This is only sound for the very first deposit**
      since every other leaf has at least one non-zero sibling. The
      ``source`` field flags the case so reviewers can audit it.

    The hash function used here is ``sha256(left || right)`` — a
    placeholder until the on-chain Poseidon helper is exposed via
    Phase 4 (the Noir circuit uses the same hash family). Withdraw
    proofs built against this path will only verify once both sides
    converge; this endpoint is therefore a *layout* contract for the
    frontend rather than a numerically correct witness today.
    """

    # 1. Load the leaf and earlier commitments from Mongo.
    cursor = (
        db.commitments
        .find({"merkle_index": {"$lte": leaf_index}}, {"_id": 0, "merkle_index": 1, "commitment": 1})
        .sort("merkle_index", 1)
    )
    commitments: list[bytes] = []
    found_target = False
    async for doc in cursor:
        idx = doc.get("merkle_index")
        commit_hex = doc.get("commitment", "")
        if not isinstance(idx, int) or not isinstance(commit_hex, str):
            continue
        if commit_hex.startswith("0x"):
            commit_hex = commit_hex[2:]
        try:
            commit_bytes = bytes.fromhex(commit_hex)
        except ValueError:
            commit_bytes = b"\x00" * 32
        commit_bytes = commit_bytes.rjust(32, b"\x00")[-32:]
        # Pad gaps with zero leaves so the index→position mapping is
        # stable even if Mongo missed an event.
        while len(commitments) < idx:
            commitments.append(b"\x00" * 32)
        commitments.append(commit_bytes)
        if idx == leaf_index:
            found_target = True

    if not commitments:
        # First-deposit fallback: every sibling is the empty subtree.
        # This is documented as "only safe for leaf_index=0" — the
        # frontend surfaces the warning to the user.
        return {
            "leaf_index": leaf_index,
            "depth": _MERKLE_TREE_DEPTH,
            "siblings": ["00" * 32] * _MERKLE_TREE_DEPTH,
            "is_left": [(leaf_index >> level) & 1 == 0 for level in range(_MERKLE_TREE_DEPTH)],
            "source": "fallback-empty",
        }

    if not found_target:
        raise NotFoundError(
            "leaf_index not yet recorded in db.commitments.",
            details={"leaf_index": leaf_index, "indexed_count": len(commitments)},
        )

    # 2. Replay the incremental insertion. ``filled[level]`` holds the
    # current "filled left-sibling" at each tree depth, exactly mirroring
    # the on-chain ``filled_subtrees`` cache. The sibling we record is
    # the one the on-chain verifier expects: zero if the leaf is on the
    # left, the cached filled subtree if it is on the right.
    siblings: list[bytes] = []
    is_left: list[bool] = []

    # Walk only up to the target leaf index; we don't need siblings for
    # later leaves because they don't affect the path of an earlier one.
    target_path: list[bytes] = [b"\x00" * 32 for _ in range(_MERKLE_TREE_DEPTH)]
    target_is_left: list[bool] = [True for _ in range(_MERKLE_TREE_DEPTH)]
    filled: list[bytes] = [b"\x00" * 32 for _ in range(_MERKLE_TREE_DEPTH)]
    zeros: list[bytes] = [b"\x00" * 32 for _ in range(_MERKLE_TREE_DEPTH)]

    for idx, leaf in enumerate(commitments):
        current = leaf
        index_at_level = idx
        for level in range(_MERKLE_TREE_DEPTH):
            on_left = (index_at_level & 1) == 0
            if idx == leaf_index:
                target_is_left[level] = on_left
                target_path[level] = filled[level] if on_left else zeros[level]
            if on_left:
                # Cache as filled left-sibling, sibling is empty.
                filled[level] = current
                current = _hash_pair(current, zeros[level])
            else:
                # Combine with stored left sibling, then bubble up.
                current = _hash_pair(filled[level], current)
            index_at_level >>= 1

    siblings = target_path
    is_left = target_is_left

    return {
        "leaf_index": leaf_index,
        "depth": _MERKLE_TREE_DEPTH,
        "siblings": [s.hex() for s in siblings],
        "is_left": is_left,
        "source": "reconstructed",
    }


def _hash_pair(left: bytes, right: bytes) -> bytes:
    """sha256(left || right) — placeholder until Poseidon helper lands."""

    import hashlib

    return hashlib.sha256(left + right).digest()


@router.get("/merkle/root")
async def get_merkle_root(
    indexer: MerkleIndexer = Depends(_make_indexer),
) -> dict[str, Any]:
    """Return the current root + the 10 most recent roots from the cache."""

    recent = await indexer.get_recent_roots(limit=_RECENT_ROOTS_LIMIT)
    if recent:
        return {
            "current": recent[0].root,
            "recent": [r.root for r in recent],
            "source": recent[0].source,
            "program_id": settings.bagsvault_program_id,
        }
    return {
        "current": _FALLBACK_ROOT,
        "recent": [],
        "source": "fallback",
        "program_id": settings.bagsvault_program_id,
    }
