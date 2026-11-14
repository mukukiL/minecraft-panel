import os
from types import SimpleNamespace

import pytest
from conftest import API, ORIGIN, sign_in

from app import game_config
from app.errors import Problem

PATH = API + "/server/config"


def test_properties_preview_and_patch_preserve_unrelated_content():
    original = (
        b"# comment\r\nmotd=old\r\nm\\u006ftd: old\\\r\n  continued\r\n"
        b"rcon.password=secret-fixture\r\nmax-players 12\r\nextra=a\\:b"
    )
    parts = game_config.entries(original)
    values = game_config.selected(parts)
    assert values == {"motd": "oldcontinued", "max-players": "12"}
    changes = {"motd": "欢迎 = §a 🐱", "max-players": "20"}
    game_config.validate_changes(values, changes)
    updated = game_config.replace_entries(original, parts, changes)
    assert game_config.selected(game_config.entries(updated)) == changes
    assert b"# comment\r\nmotd=old\r\n" in updated
    assert b"rcon.password=secret-fixture\r\n" in updated
    assert updated.endswith(b"extra=a\\:b")
    assert b"\n" not in updated.replace(b"\r\n", b"")

    for change in (
        {"rcon.password": "no"},
        {"server-port": "25566"},
        {"max-players": "0"},
        {"motd": "hello\nonline-mode=false"},
        {"view-distance": "10"},
    ):
        with pytest.raises(Problem, match="CONFIG_INVALID_VALUE"):
            game_config.validate_changes(values, change)


def test_config_routes_require_admin_origin_and_csrf(panel, monkeypatch):
    assert panel.client.get(PATH).status_code == 401
    operator, _ = sign_in(panel, "operator")
    assert panel.client.get(PATH).status_code == 403
    payload = {"revision": "a" * 64, "changes": {"max-players": "12"}}
    assert panel.client.patch(PATH, headers=operator, json=payload).status_code == 403
    headers, _ = sign_in(panel)
    assert panel.client.patch(PATH, headers={"Origin": ORIGIN}, json=payload).status_code == 403
    assert panel.client.patch(PATH, headers=headers, json=payload).status_code == 409
    monkeypatch.setattr(game_config, "manage_file", lambda *_: {"restart_required": True})
    response = panel.client.patch(PATH, headers=headers, json=payload)
    assert response.status_code == 200


@pytest.mark.skipif(os.name != "posix", reason="Linux directory descriptors")
def test_config_file_stale_restore_and_symlink(tmp_path):
    path = tmp_path / "server.properties"
    path.write_bytes(b"motd=Original\nmax-players=10\nrcon.password=secret-fixture\n")
    state = SimpleNamespace(profile=SimpleNamespace(server_dir=tmp_path))
    original = game_config.manage_file(state)
    assert len(original["fields"]) == 2
    updated = game_config.manage_file(state, original["revision"], {"max-players": "12"})
    assert updated["restart_required"]
    assert updated["restore"] == [{"key": "max-players", "after": "12", "before": "10"}]
    with pytest.raises(Problem, match="CONFIG_STALE"):
        game_config.manage_file(state, original["revision"], {"max-players": "14"})
    path.write_bytes(path.read_bytes() + b"# external change\n")
    current = game_config.manage_file(state)
    game_config.manage_file(state, current["revision"])
    assert b"max-players=10\n" in path.read_bytes()
    assert b"rcon.password=secret-fixture\n# external change\n" in path.read_bytes()
    assert b"secret-fixture" not in (tmp_path / game_config.BACKUP).read_bytes()
    other = tmp_path / "other"
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(Problem, match="CONFIG_UNAVAILABLE"):
        game_config.manage_file(state)
