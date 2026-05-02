"""slowapi-based rate limiter, keyed on client IP.

Configured for opt-in usage: import :data:`limiter` and decorate the
endpoints that need protection (typically writes / expensive scans). Wire
the exception handler into the FastAPI app so 429 responses look like the
rest of our error envelope.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings


def _default_limit_string() -> str:
    return f"{settings.rate_limit_per_minute}/minute"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_default_limit_string()],
    headers_enabled=True,
)


def rate_limit_exceeded_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    """FastAPI/Starlette handler for slowapi's RateLimitExceeded."""

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limited",
                "message": "Too many requests.",
                "details": {"limit": str(exc.detail)},
            }
        },
    )
