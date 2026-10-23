"""ASGI middlewares: request IDs and access logs, request body size limit.

Written as plain ASGI middlewares rather than with ``BaseHTTPMiddleware``, which
runs the application in another task and would lose the context variables.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from uaw.logging_config import request_id_var

logger = logging.getLogger("uaw.access")

REQUEST_ID_HEADER = "X-Request-ID"
# A request ID sent by a client or a proxy is reused only if it is short and safe to
# write in logs; otherwise a new one is generated.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Probes called every few seconds: not worth an access log line.
_QUIET_PATHS = frozenset({"/health", "/health/ready"})


class RequestContextMiddleware:
    """Gives each request an ID (logs and ``X-Request-ID`` response header) and logs
    one line per request with its status and duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500  # if the application fails before responding

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            if scope["path"] not in _QUIET_PATHS:
                duration_ms = round((time.perf_counter() - started) * 1000)
                logger.info(
                    "%s %s %d %dms",
                    scope["method"],
                    scope["path"],
                    status_code,
                    duration_ms,
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status_code,
                        "duration_ms": duration_ms,
                    },
                )
            request_id_var.reset(token)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


class MaxBodySizeMiddleware:
    """Rejects request bodies larger than ``max_bytes`` with a 413, before the
    application reads them, whether or not the client declared a Content-Length."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # The bodies of this API are small JSON documents: buffering them is cheap.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                response = JSONResponse(
                    {"detail": f"The request body exceeds {self.max_bytes} bytes."},
                    status_code=413,
                )
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()  # later calls wait for the disconnect, as usual

        await self.app(scope, replay, send)
