"""Pure-ASGI middleware for request-id binding via contextvars.

NOT BaseHTTPMiddleware — that breaks contextvars in some Starlette versions.
"""
from __future__ import annotations

import uuid

from structlog.contextvars import bind_contextvars, clear_contextvars


class RequestIdMiddleware:
    __slots__ = ("app",)

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        clear_contextvars()
        try:
            raw = dict(scope.get("headers", []))
            request_id = (
                raw.get(b"x-request-id")
                or raw.get(b"X-Request-Id")
                or uuid.uuid4().hex
            )
            if isinstance(request_id, bytes):
                request_id = request_id.decode()

            method = scope.get("method", "?")
            path = scope.get("path", "/")
            bind_contextvars(request_id=request_id, method=method, route=path)

            async def send_with_id(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", request_id.encode()))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_id)
        finally:
            clear_contextvars()
