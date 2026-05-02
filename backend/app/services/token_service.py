"""Token service: manages the project-token registry in ``db.tokens``.

The registry is the canonical source for "which tokens has this BagsVault
deployment seen?" — including the special ``$VAULT`` governance token. Live
upstream metadata is fetched best-effort from Bags and cached on the row.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.clients.bags_api import BagsAPIClient
from app.config import settings
from app.exceptions import ConflictError, NotFoundError
from app.models.token import ProjectToken, TokenRegister

logger = logging.getLogger(__name__)


# Tiny in-process TTL cache for upstream Bags metadata. Cap is small on
# purpose — a real deployment would replace this with Redis. We use a 60s
# TTL so frontend refreshes don't hammer the upstream.
_METADATA_TTL_SECONDS = 60.0
_metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


def _to_doc(token: ProjectToken) -> dict[str, Any]:
    return token.model_dump()


def _from_doc(doc: dict[str, Any]) -> ProjectToken:
    clean = _strip_id(doc)
    if isinstance(clean.get("registered_at"), str):
        clean["registered_at"] = datetime.fromisoformat(clean["registered_at"])
    return ProjectToken(**clean)


class TokenService:
    """Coordinates the ``db.tokens`` registry and Bags metadata enrichment."""

    def __init__(self, db: AsyncIOMotorDatabase, client: BagsAPIClient) -> None:
        self._db = db
        self._client = client

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def register(self, payload: TokenRegister) -> ProjectToken:
        """Idempotently register a project token.

        Same ``(mint, creator_wallet)`` returns the existing record. Same
        ``mint`` with a different ``creator_wallet`` raises
        :class:`ConflictError` (HTTP 409).
        """

        existing_doc = await self._db.tokens.find_one({"mint": payload.mint})
        if existing_doc:
            existing = _from_doc(existing_doc)
            if existing.creator_wallet != payload.creator_wallet:
                raise ConflictError(
                    "Mint already registered to a different creator.",
                    details={
                        "mint": payload.mint,
                        "registered_creator": existing.creator_wallet,
                    },
                )
            return existing

        is_vault = bool(settings.vault_token_mint and payload.mint == settings.vault_token_mint)
        token = ProjectToken(
            mint=payload.mint,
            creator_wallet=payload.creator_wallet,
            symbol=payload.symbol,
            name=payload.name,
            decimals=payload.decimals,
            metadata_uri=payload.metadata_uri,
            is_vault_token=is_vault,
        )
        await self._db.tokens.insert_one(_to_doc(token))

        # Best-effort: link the token to the creator profile.
        try:
            await self._db.creators.update_one(
                {"wallet": payload.creator_wallet},
                {
                    "$setOnInsert": {
                        "wallet": payload.creator_wallet,
                        "created_at": datetime.now(timezone.utc),
                    },
                    "$addToSet": {"tokens": payload.mint},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.info("creator upsert failed (non-fatal): %s", exc)

        logger.info(
            "token.register mint=%s creator=%s symbol=%s",
            token.mint,
            token.creator_wallet,
            token.symbol,
        )
        return token

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    async def get(self, mint: str) -> ProjectToken:
        doc = await self._db.tokens.find_one({"mint": mint})
        if not doc:
            raise NotFoundError(
                f"No token registered with mint {mint}.",
                details={"mint": mint},
            )
        return _from_doc(doc)

    async def get_with_metadata(self, mint: str) -> dict[str, Any]:
        """Return the registry row plus best-effort live Bags metadata.

        Live metadata is cached for 60 seconds in-process. If the upstream
        is unconfigured or unreachable we still return the registry row
        with ``bags_metadata`` set to ``None`` and a ``metadata_error``
        sibling explaining why.
        """

        token = await self.get(mint)
        live, error = await self._fetch_live_metadata(mint)
        out = token.model_dump()
        out["bags_metadata"] = live
        if error:
            out["metadata_error"] = error
        return out

    async def get_vault(self) -> ProjectToken:
        """Return the ``$VAULT`` token row.

        Source of truth is ``settings.vault_token_mint``. When unset, raises
        :class:`NotFoundError` with a hint pointing the operator to
        ``scripts/launch_vault_token.py``.
        """

        mint = settings.vault_token_mint
        if not mint:
            raise NotFoundError(
                "VAULT_TOKEN_MINT is not set. Run scripts/launch_vault_token.py "
                "and set the resulting mint pubkey in your .env file.",
                details={"missing_env": "VAULT_TOKEN_MINT"},
            )
        return await self.get(mint)

    async def list_tokens(self, limit: int = 20, offset: int = 0) -> list[ProjectToken]:
        cursor = self._db.tokens.find().skip(offset).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [_from_doc(doc) for doc in docs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _fetch_live_metadata(self, mint: str) -> tuple[dict[str, Any] | None, str | None]:
        now = time.monotonic()
        cached = _metadata_cache.get(mint)
        if cached and (now - cached[0]) < _METADATA_TTL_SECONDS:
            return cached[1], None

        try:
            data = await self._client.get_token_metadata(mint)
        except Exception as exc:  # noqa: BLE001 — non-fatal enrichment
            logger.info("live metadata fetch failed for mint=%s (non-fatal): %s", mint, exc)
            return None, str(exc)

        _metadata_cache[mint] = (now, data)
        return data, None
