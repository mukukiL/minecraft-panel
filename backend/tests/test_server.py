import io
import os
import zipfile

import pytest
from conftest import API, ORIGIN, sign_in
from starlette.websockets import WebSocketDisconnect

from app.errors import Problem
from app.storage import staged_upload, validate_jar_name


def jar():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("fabric.mod.json", '{"id":"fixture"}')
    return out.getvalue()


def test_mock_controls_and_log(panel):
    h, _ = sign_in(panel, "operator")
    assert panel.client.post(API + "/server/start", headers=h).json()["state"] == "running"
    assert panel.client.post(API + "/server/start", headers=h).status_code == 409
    assert (
        panel.client.post(API + "/server/stop", headers=h, json={"confirm": "RESTART"}).status_code
        == 422
    )
    assert (
        panel.client.post(
            API + "/server/restart", headers=h, json={"confirm": "RESTART"}
        ).status_code
        == 200
    )
    assert (
        panel.client.post(API + "/server/stop", headers=h, json={"confirm": "STOP"}).json()["state"]
        == "stopped"
    )
    assert "模拟服务器已停止" in panel.client.get(API + "/console/logs?limit=1").json()["lines"][0]


def test_upload_validation(panel):
    headers, _ = sign_in(panel, "operator")
    headers["Content-Type"] = "application/java-archive"
    url = API + "/mods/upload/"
    for name, content, code in (
        ("fake.jar", b"PK\x03\x04bad", 415),
        ("text.txt", jar(), 422),
        ("a..jar", jar(), 422),
        ("oversized.jar", bytes(1025), 413),
    ):
        assert panel.client.put(url + name, headers=headers, content=content).status_code == code
    result = panel.client.put(url + "mod.jar", headers=headers, content=jar())
    assert result.status_code == 201
    assert result.json()["enabled"] is False
    assert result.json()["location"] == "simulated"
    chunked = panel.client.put(url + "chunked.jar", headers=headers, content=iter([bytes(600)] * 2))
    assert chunked.status_code == 413


@pytest.mark.parametrize(
    "name", ["../a.jar", "/a.jar", "C:\\test.jar", "a%2f.jar", "CON.jar", "a\0.jar"]
)
def test_upload_rejects_unsafe_names(name):
    with pytest.raises(Problem, match="INVALID_JAR_NAME"):
        validate_jar_name(name)


@pytest.mark.skipif(os.name != "posix", reason="Linux dirfd storage")
def test_upload_nofollow_and_no_overwrite(tmp_path):
    root, outside = tmp_path / "server", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    disabled = root / "mods-disabled"
    disabled.symlink_to(outside, target_is_directory=True)
    with (
        pytest.raises(Problem, match="UPLOAD_STORAGE_UNAVAILABLE"),
        staged_upload(root, "mod.jar", 1024),
    ):
        pytest.fail("opened a symlink directory")
    disabled.unlink()
    disabled.mkdir()
    (disabled / "mod.jar").symlink_to(outside / "mod.jar")
    with (
        pytest.raises(Problem, match="MOD_EXISTS"),
        staged_upload(root, "mod.jar", 1024) as (file, publish),
    ):
        file.append(jar())
        file.finish()
        publish()
    assert list(outside.iterdir()) == []
    assert not list(disabled.glob(".upload-*"))


def test_websocket_origin_cookie_single_use(panel):
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        panel.client.websocket_connect("/ws", headers={"Origin": ORIGIN}),
    ):
        pytest.fail("accepted anonymous connection")
    assert exc.value.code == 4401
    h, _ = sign_in(panel, "viewer")
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        panel.client.websocket_connect("/ws", headers={"Origin": "https://other.test"}),
    ):
        pytest.fail("accepted cross-origin connection")
    assert exc.value.code == 4403
    result = panel.client.post(API + "/auth/ws-ticket", headers=h)
    frame = {"type": "auth", "ticket": result.json()["ticket"]}
    with panel.client.websocket_connect("wss://panel.test/ws", headers={"Origin": ORIGIN}) as ws:
        ws.send_json(frame)
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json()["type"] == "logs"
    with panel.client.websocket_connect("wss://panel.test/ws", headers={"Origin": ORIGIN}) as ws:
        ws.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_websocket_closes_after_logout(panel):
    h, _ = sign_in(panel)
    ticket = panel.client.post(API + "/auth/ws-ticket", headers=h).json()["ticket"]
    with panel.client.websocket_connect("wss://panel.test/ws", headers={"Origin": ORIGIN}) as ws:
        ws.send_json({"type": "auth", "ticket": ticket})
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json()["type"] == "logs"
        assert panel.client.post(API + "/auth/logout", headers=h).status_code == 204
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
