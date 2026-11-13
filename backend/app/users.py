from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import (
    Password,
    Payload,
    Role,
    Username,
    audit,
    cookie_token,
    hash_password,
    lookup,
    public_user,
    require_csrf,
    require_scope,
)
from app.db import LoginSession, User, write
from app.errors import Problem

router = APIRouter(prefix="/users")
Admin = Annotated[User, Depends(require_scope("users.admin"))]
UserId = Annotated[int, Path(ge=1, le=2**63 - 1)]


class CreateUser(Payload):
    username: Username
    password: Password
    role: Role


class UpdateUser(Payload):
    enabled: bool | None = None
    role: Role | None = None


class ResetPassword(Payload):
    password: Password


def actor_for(db, request: Request) -> User:
    actor, _ = lookup(db, request.app.state.settings, cookie_token(request))
    if actor.role != "admin":
        raise Problem(403, "FORBIDDEN")
    return actor


def get_user(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise Problem(404, "USER_NOT_FOUND")
    return user


@router.get("")
def list_users(
    request: Request,
    actor: Admin,
    after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> dict:
    with Session(request.app.state.engine) as db:
        rows = list(db.scalars(select(User).where(User.id > after).order_by(User.id).limit(101)))
        return {
            "items": [public_user(user) for user in rows[:100]],
            "next_cursor": rows[99].id if len(rows) > 100 else None,
        }


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def create_user(payload: CreateUser, request: Request, actor: Admin) -> dict:
    username = payload.username.lower()
    encoded = hash_password(username, payload.password.get_secret_value())
    with write(request.app.state.engine) as db:
        actor = actor_for(db, request)
        if db.scalar(select(User.id).where(User.username == username)) is not None:
            raise Problem(409, "USERNAME_TAKEN")
        user = User(username=username, password_hash=encoded, role=payload.role, enabled=True)
        db.add(user)
        db.flush()
        audit(db, "user.create", actor.id, str(user.id))
        return public_user(user)


@router.patch("/{user_id}", dependencies=[Depends(require_csrf)])
def update_user(user_id: UserId, payload: UpdateUser, request: Request, actor: Admin) -> dict:
    if payload.enabled is None and payload.role is None:
        raise Problem(422, "INVALID_INPUT")
    with write(request.app.state.engine) as db:
        actor = actor_for(db, request)
        user = get_user(db, user_id)
        enabled = user.enabled if payload.enabled is None else payload.enabled
        role = user.role if payload.role is None else payload.role
        if user.enabled and user.role == "admin" and (not enabled or role != "admin"):
            count = db.scalar(
                select(func.count()).select_from(User).where(User.role == "admin", User.enabled),
            )
            if count == 1:
                raise Problem(409, "LAST_ACTIVE_ADMIN")
        if enabled != user.enabled or role != user.role:
            user.enabled, user.role = enabled, role
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            audit(db, "user.update", actor.id, str(user.id))
        return public_user(user)


@router.post("/{user_id}/password", status_code=204, dependencies=[Depends(require_csrf)])
def reset_password(user_id: UserId, payload: ResetPassword, request: Request, actor: Admin) -> None:
    engine = request.app.state.engine
    with Session(engine) as db:
        username = get_user(db, user_id).username
    encoded = hash_password(username, payload.password.get_secret_value())
    with write(engine) as db:
        actor = actor_for(db, request)
        user = get_user(db, user_id)
        user.password_hash = encoded
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        audit(db, "user.password", actor.id, str(user.id))
