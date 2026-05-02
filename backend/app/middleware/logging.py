"""Structured request logging middleware.

Tags every request with a request id (echoed back via the ``X-Request-ID``
response header) and logs a single structured JSON line per request with the
method, path, status, and latency in milliseconds.
"""

from __future__ import annotations

import logging
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Configure structlog once at import time. Keeps stdlib logging as the
# rendering target so anything else in the app (uvicorn, motor, etc.) shares
# the same pipeline.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

_log = structlog.get_logger("bagsvault.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a request id and emit a single structured access log per request."""

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(self._header_name) or str(uuid.uuid4())
        request.state.request_id = request_id
        # Bind the request id to structlog's contextvars so anything logging
        # inside the request handler picks it up automatically.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[self._header_name] = request_id
            return response
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            _log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=status_code,
                latency_ms=round(latency_ms, 2),
                client=request.client.host if request.client else None,
            )
