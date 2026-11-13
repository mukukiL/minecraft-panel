import asyncio
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app.auth import Payload, audit, cookie_token, lookup, require_csrf, require_scope
from app.db import User, write
from app.errors import Problem
from app.storage import staged_upload, tail, validate_jar_name

if os.name == "posix":
    import fcntl

router = APIRouter()
Viewer = Annotated[User, Depends(require_scope("server.view"))]
Reader = Annotated[User, Depends(require_scope("console.read"))]
Operator = Annotated[User, Depends(require_scope("server.control"))]
Uploader = Annotated[User, Depends(require_scope("mods.write"))]
Action = Literal["start", "stop", "restart"]


class Confirm(Payload):
    confirm: Literal["STOP", "RESTART"]


@contextmanager
def control_lock(state):
    # The in-memory lock covers all platforms. flock also guards multiple Linux processes.
    if state.profile is None:
        yield
        return
    with state.settings.db_path.with_name("control.lock").open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Problem(409, "CONTROL_BUSY") from None
        yield


async def wait_for(adapter, expected: str, timeout: int) -> None:
    try:
        async with asyncio.timeout(timeout):
            while True:
                status = await adapter.status()
                if status == expected:
                    return
                await asyncio.sleep(0.5)
    except TimeoutError:
        raise Problem(504, f"SERVER_{expected.upper()}_TIMEOUT") from None


def operation_audit(state, event: str, actor: int, outcome: str) -> None:
    with write(state.engine) as db:
        audit(db, event, actor, outcome=outcome)


def authorize_action(state, token: str, event: str | None = None) -> int:
    with write(state.engine) as db:
        user, _ = lookup(db, state.settings, token)
        if user.role not in ("admin", "operator"):
            raise Problem(403, "FORBIDDEN")
        if event is not None:
            audit(db, event, user.id, outcome="requested")
        return user.id


@router.get("/server/status")
async def status(request: Request, user: Viewer) -> dict:
    state = request.app.state
    adapter = state.adapter
    return {
        "state": await adapter.status(),
        "adapter": adapter.kind,
        "controls": list(adapter.controls) if user.role != "viewer" else [],
        "upload_available": user.role != "viewer"
        and (state.profile is not None or adapter.kind == "mock"),
    }


async def control(action: Action, request: Request) -> dict:
    state = request.app.state
    adapter = state.adapter
    event = f"server.{action}"
    if action not in adapter.controls:
        raise Problem(409, "CONTROL_UNAVAILABLE")
    if state.control.locked():
        raise Problem(409, "CONTROL_BUSY")
    async with state.control:
        with control_lock(state):
            token = cookie_token(request)
            actor = await run_in_threadpool(authorize_action, state, token, event)
            try:
                if action in ("stop", "restart"):
                    await adapter.stop()
                    await wait_for(
                        adapter, "stopped", state.profile.stop_timeout if state.profile else 1
                    )
                if action in ("start", "restart"):
                    if action == "restart":
                        await run_in_threadpool(authorize_action, state, token)
                    await adapter.start()
                    await wait_for(
                        adapter, "running", state.profile.start_timeout if state.profile else 1
                    )
            except Problem:
                await run_in_threadpool(operation_audit, state, event, actor, "failed")
                raise
            await run_in_threadpool(operation_audit, state, event, actor, "ok")
            return {"state": "stopped" if action == "stop" else "running"}


@router.post("/server/start", dependencies=[Depends(require_csrf)])
async def start(request: Request, user: Operator, payload: Payload | None = None) -> dict:
    return await control("start", request)


@router.post("/server/stop", dependencies=[Depends(require_csrf)])
async def stop(payload: Confirm, request: Request, user: Operator) -> dict:
    if payload.confirm != "STOP":
        raise Problem(422, "CONFIRMATION_REQUIRED")
    return await control("stop", request)


@router.post("/server/restart", dependencies=[Depends(require_csrf)])
async def restart(payload: Confirm, request: Request, user: Operator) -> dict:
    if payload.confirm != "RESTART":
        raise Problem(422, "CONFIRMATION_REQUIRED")
    return await control("restart", request)


def recent_logs(state, limit: int) -> list[str]:
    if state.profile is not None:
        return tail(Path(state.profile.server_dir), limit)
    return state.adapter.logs[-limit:] if state.adapter.kind == "mock" else []


@router.get("/console/logs")
def logs(request: Request, user: Reader, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> dict:
    return {"lines": recent_logs(request.app.state, limit)}


@router.put("/mods/upload/{filename}", status_code=201, dependencies=[Depends(require_csrf)])
async def upload(filename: str, request: Request, user: Uploader) -> dict:
    validate_jar_name(filename)
    state = request.app.state
    if state.profile is None and state.adapter.kind != "mock":
        raise Problem(409, "PROFILE_UNCONFIGURED")
    if request.headers.get("content-type") != "application/java-archive":
        raise Problem(415, "EXPECTED_JAR_CONTENT_TYPE")
    length = request.headers.get("content-length")
    if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 12):
        raise Problem(400, "INVALID_CONTENT_LENGTH")
    if length is not None and int(length) > state.settings.upload_limit:
        raise Problem(413, "UPLOAD_TOO_LARGE")
    if state.upload.locked():
        raise Problem(409, "UPLOAD_BUSY")
    token = cookie_token(request)
    root = Path(state.profile.server_dir) if state.profile else None
    async with state.upload:
        try:
            async with asyncio.timeout(120):
                with staged_upload(root, filename, state.settings.upload_limit) as (file, publish):
                    async for chunk in request.stream():
                        await run_in_threadpool(file.append, chunk)
                    sha256 = await run_in_threadpool(file.finish)
                    await run_in_threadpool(publish_upload, state, token, filename, publish)
        except ClientDisconnect:
            raise Problem(400, "UPLOAD_INTERRUPTED") from None
        except TimeoutError:
            raise Problem(408, "UPLOAD_TIMEOUT") from None
    return {
        "filename": filename,
        "size": file.size,
        "sha256": sha256,
        "enabled": False,
        "location": "disabled" if root else "simulated",
    }


def publish_upload(state, token, filename, publish) -> None:
    with write(state.engine) as db:
        user, _ = lookup(db, state.settings, token)
        if user.role not in ("operator", "admin"):
            raise Problem(403, "FORBIDDEN")
        publish()
        audit(db, "mod.upload", user.id, filename)
