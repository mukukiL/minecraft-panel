from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.config import Settings
from app.db import database
from app.main import create_app


def test_health_and_production_https(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("MC_PANEL_DB_PATH", str(path))
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    settings = Settings(env="production", public_origin="https://panel.test", db_path=path)
    with TestClient(create_app(settings), base_url="https://panel.test") as client:
        result = client.get("/healthz")
        assert result.json() == {"ok": True}
        assert result.headers["X-Request-ID"]
        assert client.get("/docs").status_code == 404
        denied = client.get("http://panel.test/healthz")
        assert denied.json()["code"] == "HTTPS_REQUIRED"
    command.downgrade(config, "base")
    engine = database(path)
    try:
        assert not {"users", "sessions", "audit_logs"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
