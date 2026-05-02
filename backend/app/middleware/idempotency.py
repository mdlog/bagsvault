"""Idempotency-Key handling middleware.

Implemented as Starlette middleware (rather than a FastAPI dependency)
because the upstream value proposition is *transparent* — if a client
retries a write with the same ``Idempotency-Key`` and identical body,
they should get the exact response from the first call without the
handler running again. Doing this from a dependency would require every
write endpoint to opt in and would not help endpoints that mutate state
before validation.

Storage lives in ``db.idempotency_keys`` (TTL 24h, see
:func:`app.database.ensure_indexes`). Each record holds:

    {
        "key": <idempotency-key>,
        "body_hash": <sha256 hex of request body>,
        "method": <method>,
        "path": <path>,
        "status_code": <int>,
        "response_body": <bytes>,
        "response_headers": [[name, value], ...],
        "created_at": <utc datetime>,
    }

If the key reappears with a different body hash on the same method/path,
we surface :class:`ConflictError` so the client knows to use a fresh key.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.database import get_db
from app.exceptions import ConflictError

logger = logging.getLogger(__name__)

_IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}
_HEADER = "Idempotency-Key"


def _hash_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Cache responses keyed on the ``Idempotency-Key`` header for unsafe methods."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method.upper() not in _IDEMPOTENT_METHODS:
            return await call_next(request)

        key = request.headers.get(_HEADER)
        if not key:
            return await call_next(request)

        body = await request.body()
        body_hash = _hash_body(body)

        db = get_db()
        existing = await db.idempotency_keys.find_one({"key": key})
        if existing:
            if existing.get("body_hash") != body_hash:
                raise ConflictError(
                    "Idempotency-Key reused with a different request body.",
                    details={"key": key},
                )
            logger.info("idempotency.cache_hit key=%s", key)
            return _replay_response(existing)

        # Re-prime the request body since we've already consumed it via .body().
        async def _receive() -> dict[str, object]:
            return {"type": "http.request", "body": body, "more_body": False}

        setattr(request, "_receive", _receive)

        response = await call_next(request)

        # Buffer the response body so we can both forward and persist it.
        # ``body_iterator`` is only present on streaming responses; plain
        # ``Response`` exposes ``.body`` directly.
        response_body = b""
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is not None:
            async for chunk in body_iterator:
                response_body += chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
        else:
            raw_body = getattr(response, "body", b"")
            if isinstance(raw_body, str):
                response_body = raw_body.encode("utf-8")
            elif isinstance(raw_body, (bytes, bytearray, memoryview)):
                response_body = bytes(raw_body)

        record = {
            "key": key,
            "body_hash": body_hash,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "response_body": response_body,
            "response_headers": [list(item) for item in response.headers.raw],
            "created_at": datetime.now(timezone.utc),
        }
        try:
            await db.idempotency_keys.insert_one(record)
        except DuplicateKeyError:
            # Concurrent request beat us to the insert — that's fine, the
            # response we generated is still valid for this caller.
            logger.info("idempotency.race key=%s", key)

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


def _replay_response(record: dict[str, object]) -> Response:
    raw_body = record.get("response_body")
    body: bytes
    if isinstance(raw_body, (bytes, bytearray, memoryview)):
        body = bytes(raw_body)
    elif isinstance(raw_body, str):
        body = raw_body.encode("utf-8")
    else:
        body = b""

    headers_raw = record.get("response_headers")
    headers: dict[str, str] = {}
    if isinstance(headers_raw, list):
        for item in headers_raw:
            try:
                name, value = item
            except (TypeError, ValueError):
                continue
            if isinstance(name, (bytes, bytearray)):
                name = name.decode("latin-1")
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("latin-1")
            headers[str(name)] = str(value)

    raw_status = record.get("status_code")
    status_code = raw_status if isinstance(raw_status, int) else 200

    # If the cached body parses as JSON, return JSONResponse so content-type
    # stays correct; otherwise fall back to a raw Response.
    parsed_json: object = None
    is_json = False
    try:
        parsed_json = json.loads(body)
        is_json = True
    except (TypeError, ValueError):
        pass

    if is_json:
        return JSONResponse(
            content=parsed_json,
            status_code=status_code,
            headers=headers,
        )
    return Response(content=body, status_code=status_code, headers=headers)
