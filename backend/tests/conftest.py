import secrets
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.config import Settings
from app.db import User, write
from app.main import create_app

ORIGIN = "https://panel.test"
API = "/api/v1"


@pytest.fixture
def panel(tmp_path, monkeypatch):
    settings = Settings(
        public_origin=ORIGIN,
        db_path=tmp_path / "panel.db",
        upload_limit=1024,
    )
    monkeypatch.setenv("MC_PANEL_DB_PATH", str(settings.db_path))
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(settings)
    password = secrets.token_urlsafe(24)
    with TestClient(app, base_url=ORIGIN) as client:
        encoded = hash_password("fixture", password)
        with write(app.state.engine) as db:
            db.add_all(
                [
                    User(username=role, password_hash=encoded, role=role)
                    for role in ("admin", "viewer", "operator")
                ]
            )
        yield SimpleNamespace(client=client, app=app, password=password, settings=settings)


def sign_in(panel, role="admin", client=None):
    client = client if client is not None else panel.client
    response = client.post(
        API + "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": role, "password": panel.password},
    )
    assert response.status_code == 200, response.text
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}, response
