import asyncio
from collections import deque

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings


class RequestLimits:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self.settings.env == "production" and scope["scheme"] != "https":
            await self.reject(scope, receive, send, 400, "HTTPS_REQUIRED")
            return
        if scope["method"] not in {"POST", "PATCH", "PUT", "DELETE"} or (
            scope["method"] == "PUT" and scope["path"].startswith("/api/v1/mods/upload/")
        ):
            await self.app(scope, receive, send)
            return

        chunks: deque = deque()
        total = 0
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    total += len(message.get("body", b""))
                    if total > 8192 or len(chunks) >= 128:
                        await self.reject(scope, receive, send, 413, "BODY_TOO_LARGE")
                        return
                    chunks.append(message)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self.reject(scope, receive, send, 408, "BODY_TIMEOUT")
            return
        if (
            total
            and Headers(scope=scope).get("content-type", "").split(";")[0] != "application/json"
        ):
            await self.reject(scope, receive, send, 415, "EXPECTED_JSON")
            return

        async def replay():
            return chunks.popleft() if chunks else await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def reject(scope: Scope, receive: Receive, send: Send, status: int, code: str) -> None:
        response = JSONResponse(
            {
                "type": "about:blank",
                "status": status,
                "code": code,
                "title": code.replace("_", " ").title(),
                "request_id": scope["state"]["request_id"],
            },
            status_code=status,
            media_type="application/problem+json",
        )
        await response(scope, receive, send)
