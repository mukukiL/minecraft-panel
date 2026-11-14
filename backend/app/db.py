import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    URL,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','operator','viewer')"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    last_seen: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[int] = mapped_column(Integer, index=True)
    event: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(16))


class SiteBranding(Base):
    __tablename__ = "site_branding"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    portrait: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    background: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    revision: Mapped[int] = mapped_column(Integer)


def database(path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    engine = create_engine(URL.create("sqlite", database=str(path)), hide_parameters=True)

    @event.listens_for(engine, "connect")
    def setup(connection, _):
        for pragma in (
            "busy_timeout=5000",
            "journal_mode=WAL",
            "foreign_keys=ON",
            "synchronous=NORMAL",
            "cache_size=-8192",
        ):
            connection.execute(f"PRAGMA {pragma}")

    return engine


@contextmanager
def write(engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as db, db.begin():
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db
