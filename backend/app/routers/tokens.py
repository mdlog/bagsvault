"""Project-token registry endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth import require_wallet
from app.clients.bags_api import BagsAPIClient, get_bags_api_client
from app.database import get_db
from app.exceptions import AuthError
from app.models.token import ProjectToken, TokenRegister
from app.services.token_service import TokenService

router = APIRouter(prefix="/tokens", tags=["tokens"])


def get_token_service(
    db: AsyncIOMotorDatabase = Depends(get_db),
    client: BagsAPIClient = Depends(get_bags_api_client),
) -> TokenService:
    return TokenService(db=db, client=client)


@router.post("/register", response_model=ProjectToken)
async def register_token(
    payload: TokenRegister,
    service: TokenService = Depends(get_token_service),
    wallet: str = Depends(require_wallet),
) -> ProjectToken:
    """Register a project token. Idempotent on ``(mint, creator_wallet)``.

    Authenticated: the SIWS-signed wallet must equal ``payload.creator_wallet``.
    """

    if wallet != payload.creator_wallet:
        raise AuthError(
            "Signed wallet does not match creator_wallet in request body.",
            details={"signed": wallet, "requested": payload.creator_wallet},
        )
    return await service.register(payload)


@router.get("/vault", response_model=ProjectToken)
async def get_vault_token(
    service: TokenService = Depends(get_token_service),
) -> ProjectToken:
    """Return the ``$VAULT`` governance token (404 if not yet launched)."""

    return await service.get_vault()


@router.get("")
async def list_tokens(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: TokenService = Depends(get_token_service),
) -> dict[str, Any]:
    """Paginated list of registered tokens."""

    items = await service.list_tokens(limit=limit, offset=offset)
    return {
        "items": [item.model_dump() for item in items],
        "limit": limit,
        "offset": offset,
        "count": len(items),
    }


@router.get("/{mint}")
async def get_token(
    mint: str,
    service: TokenService = Depends(get_token_service),
) -> dict[str, Any]:
    """Return the registry row for ``mint`` plus best-effort live Bags metadata.

    Live metadata is cached in-process for 60 seconds. When the upstream is
    unconfigured or unreachable, ``bags_metadata`` is ``null`` and a
    ``metadata_error`` field describes the cause.
    """

    return await service.get_with_metadata(mint)
