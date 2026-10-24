from __future__ import annotations

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger("business_chatbot.http")


class RequestContextMiddleware:
    """Add a traceable request ID and safe response headers to every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = next(
            (value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"x-request-id"),
            None,
        ) or str(uuid.uuid4())
        started = time.perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        scope.setdefault("state", {})["request_id"] = request_id
        try:
            await self.app(scope, receive, send_with_context)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                request_id,
                scope.get("method", ""),
                scope.get("path", ""),
                status_code,
                elapsed_ms,
            )
