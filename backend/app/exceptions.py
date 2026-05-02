"""Custom exception types and FastAPI handlers.

Use these instead of bare HTTPException to keep error responses structured and
to make it easy to filter/observe specific failure modes.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class BagsVaultError(Exception):
    """Base class for domain errors. Carries an HTTP status + machine code."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ServiceUnavailableError(BagsVaultError):
    """An upstream service we depend on is not configured or unreachable."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


class UpstreamError(BagsVaultError):
    """Upstream service returned an error response."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"


class ValidationError(BagsVaultError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_error"


class AuthError(BagsVaultError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "auth_error"


class ConflictError(BagsVaultError):
    """E.g. nullifier already spent, idempotency key reused with different body."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class NotFoundError(BagsVaultError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BagsVaultError)
    async def _bagsvault_handler(_: Request, exc: BagsVaultError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
