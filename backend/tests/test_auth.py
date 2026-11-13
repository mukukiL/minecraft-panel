import secrets

import pytest
from conftest import API, ORIGIN, sign_in
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import hash_token, now
from app.db import AuditLog, LoginSession, User, write


def test_login_secure_cookie_and_hashed_storage(panel):
    headers, response = sign_in(panel)
    cookie = response.headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"))
    assert cookie.startswith("__Host-mcpanel_session=")
    token = panel.client.cookies.get(panel.settings.cookie_name)
    with Session(panel.app.state.engine) as db:
        record = db.scalar(select(LoginSession))
        assert record.token_hash == hash_token(token)
        assert db.get(User, record.user_id).password_hash.startswith("$argon2id$")
    assert panel.client.get(API + "/auth/me").json()["csrf_token"] == headers["X-CSRF-Token"]
    assert panel.client.post(API + "/auth/logout", headers=headers).status_code == 204
    panel.client.cookies.set(panel.settings.cookie_name, token)
    assert panel.client.get(API + "/auth/me").status_code == 401


@pytest.mark.parametrize("name", ["admin", "does-not-exist"])
def test_invalid_login_uniform_and_audited(panel, name):
    result = panel.client.post(
        API + "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": name, "password": "incorrect"},
    )
    assert result.status_code == 401
    assert result.json()["code"] == "INVALID_CREDENTIALS"
    assert "set-cookie" not in result.headers
    with Session(panel.app.state.engine) as db:
        assert db.scalar(select(AuditLog).where(AuditLog.event == "login")).outcome == "denied"


def test_scope_and_anonymous(panel):
    for url in ("/auth/me", "/server/status", "/users", "/console/logs"):
        assert panel.client.get(API + url).status_code == 401
    headers, _ = sign_in(panel, "viewer")
    assert panel.client.post(API + "/server/start", headers=headers).status_code == 403
    assert panel.client.get(API + "/server/status").status_code == 200
    headers, _ = sign_in(panel, "operator")
    assert panel.client.get(API + "/users").status_code == 403
    assert (
        panel.client.patch(API + "/users/1", headers=headers, json={"enabled": False}).status_code
        == 403
    )


def test_disabled_sessions_and_password_reset(panel):
    admin_headers, _ = sign_in(panel)
    with TestClient(panel.app, base_url=ORIGIN) as second:
        sign_in(panel, "viewer", second)
        endpoint = API + "/users/2"
        assert (
            panel.client.patch(endpoint, headers=admin_headers, json={"enabled": False}).status_code
            == 200
        )
        assert second.get(API + "/auth/me").status_code == 401
        assert (
            panel.client.patch(endpoint, headers=admin_headers, json={"enabled": True}).status_code
            == 200
        )
        sign_in(panel, "viewer", second)
        new = secrets.token_urlsafe(24)
        assert (
            panel.client.post(
                endpoint + "/password", headers=admin_headers, json={"password": new}
            ).status_code
            == 204
        )
        assert second.get(API + "/auth/me").status_code == 401


@pytest.mark.parametrize("field", ["expires_at", "last_seen"])
def test_session_expiry(panel, field):
    sign_in(panel)
    with write(panel.app.state.engine) as db:
        db.execute(update(LoginSession).values({field: now() - 100_000}))
    assert panel.client.get(API + "/auth/me").status_code == 401


def test_csrf_origin_and_body_validation(panel):
    result = panel.client.post(
        API + "/auth/login", json={"username": "admin", "password": panel.password}
    )
    assert result.json()["code"] == "ORIGIN_DENIED"
    headers, _ = sign_in(panel)
    for supplied in (
        {"Origin": ORIGIN},
        {"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
        headers | {"Origin": "https://other.test"},
    ):
        assert panel.client.post(API + "/server/start", headers=supplied).status_code == 403
    bad = panel.client.post(API + "/server/start", headers=headers, json={"command": "java"})
    assert bad.status_code == 422 and "java" not in bad.text


def test_login_rate_limited(panel):
    for _ in range(5):
        assert (
            panel.client.post(
                API + "/auth/login",
                headers={"Origin": ORIGIN},
                json={"username": "admin", "password": "wrong"},
            ).status_code
            == 401
        )
    result = panel.client.post(
        API + "/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": "viewer", "password": panel.password},
    )
    assert result.status_code == 429 and result.headers["retry-after"]


def test_password_change_revokes_all_sessions(panel):
    headers, _ = sign_in(panel)
    with TestClient(panel.app, base_url=ORIGIN) as second:
        sign_in(panel, client=second)
        assert (
            panel.client.post(
                API + "/auth/password",
                headers=headers,
                json={
                    "current_password": panel.password,
                    "new_password": secrets.token_urlsafe(24),
                },
            ).status_code
            == 204
        )
        assert second.get(API + "/auth/me").status_code == 401
        assert panel.client.get(API + "/auth/me").status_code == 401


def test_last_admin_and_create_user(panel):
    headers, _ = sign_in(panel)
    for body in ({"enabled": False}, {"role": "viewer"}):
        result = panel.client.patch(API + "/users/1", headers=headers, json=body)
        assert result.json()["code"] == "LAST_ACTIVE_ADMIN"
    assert panel.client.delete(API + "/users/1", headers=headers).status_code == 405
    result = panel.client.post(
        API + "/users",
        headers=headers,
        json={
            "username": "second-admin",
            "password": secrets.token_urlsafe(24),
            "role": "admin",
        },
    )
    assert result.status_code == 201
    assert "password" not in result.text
    assert (
        panel.client.patch(API + "/users/1", headers=headers, json={"role": "viewer"}).status_code
        == 200
    )
    assert panel.client.get(API + "/auth/me").status_code == 401
