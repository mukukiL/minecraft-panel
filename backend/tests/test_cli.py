import secrets
import sys
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.auth import verify
from app.db import User, database


def test_interactive_bootstrap_only_once(tmp_path, monkeypatch):
    path = tmp_path / "panel.db"
    monkeypatch.setenv("MC_PANEL_DB_PATH", str(path))
    command.upgrade(Config("alembic.ini"), "head")
    monkeypatch.setattr(sys, "argv", ["app.cli", "create-admin"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "FirstAdmin")
    password = secrets.token_urlsafe(24)
    prompt = Mock(return_value=password)
    monkeypatch.setattr(cli.getpass, "getpass", prompt)
    assert cli.main() == 0
    assert prompt.call_count == 2
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    engine = database(path)
    try:
        with Session(engine) as db:
            users = list(db.scalars(select(User)))
            assert len(users) == 1
            assert users[0].username == "firstadmin" and users[0].role == "admin"
            assert verify(users[0].password_hash, password)
    finally:
        engine.dispose()
