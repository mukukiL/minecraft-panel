import asyncio
import hashlib
import json
import secrets
import time
from collections import Counter
from contextlib import suppress

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth import cookie_token, hash_token, lookup, origin_ok, require_csrf
from app.errors import Problem
from app.server import Reader, recent_logs

api = APIRouter()
sockets = APIRouter()


@api.post("/auth/ws-ticket", dependencies=[Depends(require_csrf)])
async def issue_ticket(request: Request, user: Reader) -> dict:
    state = request.app.state
    key = hash_token(cookie_token(request))
    t = time.monotonic()
    state.tickets = {digest: value for digest, value in state.tickets.items() if value[1] > t}
    if len(state.tickets) >= 200 or sum(value[0] == key for value in state.tickets.values()) >= 4:
        raise Problem(429, "TICKET_LIMIT")
    ticket = secrets.token_urlsafe(32)
    state.tickets[hash_token(ticket)] = (key, t + 30)
    return {"ticket": ticket}


def authenticate(state, token: str) -> int:
    with Session(state.engine) as db:
        return lookup(db, state.settings, token)[0].id


async def socket_auth(ws: WebSocket, state, token: str) -> None:
    try:
        frame = await asyncio.wait_for(ws.receive(), timeout=5)
        raw = frame.get("text")
        if raw is None or len(raw) > 256:
            raise ValueError
        message = json.loads(raw)
        if not isinstance(message, dict) or set(message) != {"type", "ticket"}:
            raise ValueError
        ticket = message["ticket"]
        if message["type"] != "auth" or not isinstance(ticket, str) or len(ticket) != 43:
            raise ValueError
        digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
        stored = state.tickets.get(digest)
        if stored is None or stored[0] != hash_token(token) or stored[1] <= time.monotonic():
            raise ValueError
        del state.tickets[digest]
    except (TimeoutError, ValueError):
        raise Problem(401, "WS_AUTH_DENIED") from None


@sockets.websocket("/ws")
async def logs_socket(ws: WebSocket) -> None:
    state = ws.app.state
    if not origin_ok(ws.headers, state.settings) or (
        state.settings.env == "production" and ws.url.scheme != "wss"
    ):
        await ws.close(4403)
        return
    try:
        token = cookie_token(ws)
        if not state.socket_limiter.allow(
            ws.client.host if ws.client else "unknown",
            hash_token(token),
        ):
            await ws.close(4429)
            return
        uid = await run_in_threadpool(authenticate, state, token)
    except Problem:
        await ws.close(4401)
        return
    counts: Counter[int] = state.sockets
    if sum(counts.values()) >= 20 or counts[uid] >= 4:
        await ws.close(4429)
        return
    counts[uid] += 1
    try:
        await ws.accept()
        await socket_auth(ws, state, token)
        await asyncio.wait_for(ws.send_json({"type": "ready", "topics": ["logs"]}), timeout=3)
        last = None
        while True:
            await run_in_threadpool(authenticate, state, token)
            logs = await run_in_threadpool(recent_logs, state, 100)
            if logs != last:
                await asyncio.wait_for(ws.send_json({"type": "logs", "lines": logs}), timeout=3)
                last = logs
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=2)
            except TimeoutError:
                continue
            if msg["type"] == "websocket.disconnect":
                return
            await ws.close(1008)
            return
    except Problem:
        with suppress(RuntimeError, OSError):
            await ws.close(4401)
    except (WebSocketDisconnect, TimeoutError, OSError):
        with suppress(RuntimeError, OSError):
            await ws.close(1013)
    finally:
        counts[uid] -= 1
        if not counts[uid]:
            del counts[uid]
