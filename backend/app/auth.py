import hashlib
import re
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Literal

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import AuditLog, LoginSession, User, write
from app.errors import Problem

router = APIRouter(prefix="/auth")
Role = Literal["admin", "operator", "viewer"]
Username = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")]
Password = Annotated[SecretStr, Field(min_length=12, max_length=128)]
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
READ = {"server.view", "console.read"}
OPERATE = READ | {"server.control", "mods.write"}
SCOPES = {"viewer": READ, "operator": OPERATE, "admin": OPERATE | {"users.admin", "console.write"}}
hasher = PasswordHasher(time_cost=3, memory_cost=32_768, parallelism=1, type=Type.ID)
password_slots = threading.BoundedSemaphore(2)
WEAK = {"password1234", "password123456", "123456789012", "administrator", "qwerty123456"}


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Login(Payload):
    username: Annotated[str, Field(min_length=1, max_length=128)]
    password: Annotated[SecretStr, Field(max_length=128)]


class ChangePassword(Payload):
    current_password: Annotated[SecretStr, Field(max_length=128)]
    new_password: Password


def now() -> int:
    return int(time.time())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def csrf_for(token: str) -> str:
    # Domain separation keeps this value independent of the stored token hash.
    return hash_token("mcpanel-csrf-v1:" + token)


def hash_password(username: str, password: str) -> str:
    if (
        not 12 <= len(password) <= 128
        or not password.strip()
        or password.casefold() in WEAK | {username.casefold()}
    ):
        raise Problem(422, "WEAK_PASSWORD")
    with password_slots:
        return hasher.hash(password)


def verify(encoded: str, password: str) -> bool:
    with password_slots:
        try:
            return hasher.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            return False


class LoginLimit:
    def __init__(self, ip_limit: int = 5, user_limit: int = 10) -> None:
        self.lock = threading.Lock()
        self.hits: dict[tuple[str, str], deque[float]] = {}
        self.sweep_at = 0.0
        self.ip_limit = ip_limit
        self.user_limit = user_limit

    def allow(self, ip: str, username: str) -> bool:
        t = time.monotonic()
        with self.lock:
            if t >= self.sweep_at:
                self.hits = {key: q for key, q in self.hits.items() if q and q[-1] > t - 3600}
                self.sweep_at = t + 60
            keys = ((("ip", ip), 60, self.ip_limit), (("user", username), 3600, self.user_limit))
            queues = []
            for key, window, limit in keys:
                if key not in self.hits and len(self.hits) >= 8192:
                    return False
                q = self.hits.setdefault(key, deque())
                while q and q[0] <= t - window:
                    q.popleft()
                if len(q) >= limit:
                    return False
                queues.append(q)
            for q in queues:
                q.append(t)
            return True


def audit(db: Session, event: str, actor: int | None, target=None, outcome="ok") -> None:
    db.add(AuditLog(at=now(), event=event, actor_id=actor, target=target, outcome=outcome))


def origin_ok(headers, settings: Settings) -> bool:
    return headers.getlist("origin") == [settings.public_origin]


def require_origin(request: Request) -> None:
    if not origin_ok(request.headers, request.app.state.settings):
        raise Problem(403, "ORIGIN_DENIED")


def cookie_token(connection) -> str:
    token = connection.cookies.get(connection.app.state.settings.cookie_name, "")
    if not TOKEN.fullmatch(token):
        raise Problem(401, "AUTH_REQUIRED")
    return token


def lookup(db: Session, settings: Settings, token: str) -> tuple[User, LoginSession]:
    login = db.get(LoginSession, hash_token(token))
    t = now()
    if login is None or login.expires_at <= t or login.last_seen + settings.session_idle <= t:
        raise Problem(401, "AUTH_REQUIRED")
    user = db.get(User, login.user_id)
    if user is None or not user.enabled:
        raise Problem(401, "AUTH_REQUIRED")
    return user, login


def current_user(request: Request) -> User:
    token = cookie_token(request)
    state = request.app.state
    with Session(state.engine) as db:
        user, login = lookup(db, state.settings, token)
        # Dashboard polling does not keep an unattended browser session alive.
        background = request.url.path in {"/api/v1/server/status", "/api/v1/console/logs"}
        if not background and now() - login.last_seen >= min(
            60, max(1, state.settings.session_idle // 4)
        ):
            db.execute(
                update(LoginSession)
                .where(
                    LoginSession.token_hash == login.token_hash,
                    LoginSession.last_seen == login.last_seen,
                )
                .values(last_seen=now())
            )
            db.commit()
            db.refresh(user)
        db.expunge(user)
        return user


def require_scope(scope: str):
    def allowed(user: Annotated[User, Depends(current_user)]) -> User:
        if scope not in SCOPES[user.role]:
            raise Problem(403, "FORBIDDEN")
        return user

    return allowed


def require_csrf(request: Request) -> None:
    require_origin(request)
    value = request.headers.get("x-csrf-token", "")
    if not re.fullmatch(r"[0-9a-f]{64}", value) or not secrets.compare_digest(
        value,
        csrf_for(cookie_token(request)),
    ):
        raise Problem(403, "CSRF_DENIED")


def public_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "enabled": user.enabled,
        "scopes": sorted(SCOPES[user.role]),
    }


def auth_result(user: User, token: str, login: LoginSession) -> dict:
    return {
        "user": public_user(user),
        "csrf_token": csrf_for(token),
        "expires_at": datetime.fromtimestamp(login.expires_at, UTC).isoformat(),
    }


def clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.secure_cookie,
        httponly=True,
        samesite="strict",
    )


@router.post("/login", dependencies=[Depends(require_origin)])
def login(payload: Login, request: Request, response: Response) -> dict:
    state = request.app.state
    username = payload.username.lower()
    valid_name = re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,31}", username, re.ASCII)
    ip = request.client.host if request.client else "unknown"
    target = username if valid_name and payload.username.isascii() else None
    if not state.limiter.allow(ip, target or "<invalid>"):
        # Limit audit writes during a flood. Failed credential checks are always audited.
        raise Problem(429, "LOGIN_RATE_LIMITED", {"Retry-After": "60"})

    with Session(state.engine) as db:
        user = db.scalar(select(User).where(User.username == target)) if target else None
        encoded = user.password_hash if user else state.dummy_hash
        uid = user.id if user else None
    valid = verify(encoded, payload.password.get_secret_value())

    previous = request.cookies.get(state.settings.cookie_name, "")
    token = secrets.token_urlsafe(32)
    with write(state.engine) as db:
        user = db.get(User, uid) if uid is not None else None
        ok = bool(valid and user and user.enabled and user.password_hash == encoded)
        audit(db, "login", uid, outcome="ok" if ok else "denied")
        if ok and user is not None:
            t = now()
            db.execute(
                delete(LoginSession).where(
                    or_(
                        LoginSession.expires_at <= t,
                        LoginSession.last_seen <= t - state.settings.session_idle,
                    )
                )
            )
            if TOKEN.fullmatch(previous):
                db.execute(
                    delete(LoginSession).where(LoginSession.token_hash == hash_token(previous))
                )
            record = LoginSession(
                token_hash=hash_token(token),
                user_id=user.id,
                created_at=t,
                last_seen=t,
                expires_at=t + state.settings.session_ttl,
            )
            db.add(record)
            data = auth_result(user, token, record)
    if not ok:
        raise Problem(401, "INVALID_CREDENTIALS")
    response.set_cookie(
        state.settings.cookie_name,
        token,
        max_age=state.settings.session_ttl,
        secure=state.settings.secure_cookie,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return data


@router.get("/me")
def me(request: Request, user: Annotated[User, Depends(current_user)]) -> dict:
    state = request.app.state
    token = cookie_token(request)
    with Session(state.engine) as db:
        user, record = lookup(db, state.settings, token)
        return auth_result(user, token, record)


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response) -> None:
    state = request.app.state
    token = cookie_token(request)
    with write(state.engine) as db:
        user, record = lookup(db, state.settings, token)
        db.delete(record)
        audit(db, "logout", user.id)
    clear_cookie(response, state.settings)


@router.post("/password", status_code=204, dependencies=[Depends(require_csrf)])
def change_password(payload: ChangePassword, request: Request, response: Response) -> None:
    state = request.app.state
    token = cookie_token(request)
    with Session(state.engine) as db:
        user, _ = lookup(db, state.settings, token)
        encoded, username = user.password_hash, user.username
    if not state.password_limiter.allow(
        request.client.host if request.client else "unknown",
        username,
    ):
        raise Problem(429, "PASSWORD_RATE_LIMITED", {"Retry-After": "60"})
    if not verify(encoded, payload.current_password.get_secret_value()):
        with write(state.engine) as db:
            user, _ = lookup(db, state.settings, token)
            audit(db, "password.change", user.id, outcome="denied")
        raise Problem(403, "INVALID_CREDENTIALS")
    replacement = hash_password(username, payload.new_password.get_secret_value())
    with write(state.engine) as db:
        user, _ = lookup(db, state.settings, token)
        if user.password_hash != encoded:
            raise Problem(409, "PASSWORD_CHANGED")
        user.password_hash = replacement
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        audit(db, "password.change", user.id)
    clear_cookie(response, state.settings)
