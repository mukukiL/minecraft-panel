import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Annotated, Any

import javaproperties
from fastapi import APIRouter, Depends, Request
from pydantic import Field

from app.auth import Payload, cookie_token, require_csrf, require_scope
from app.db import User
from app.errors import Problem
from app.server import authorize_action, control_lock, operation_audit
from app.storage import open_directory

router = APIRouter(prefix="/server/config")
Admin = Annotated[User, Depends(require_scope("server.config"))]
CONFIG = "server.properties"
BACKUP = ".mc-panel-properties-backup.json"
LIMIT = 64 * 1024
FIELDS: dict[str, dict[str, Any]] = {
    "motd": {"label": "服务器简介", "kind": "text", "max_length": 160},
    "difficulty": {
        "label": "难度",
        "kind": "select",
        "choices": {"peaceful": "和平", "easy": "简单", "normal": "普通", "hard": "困难"},
    },
    "gamemode": {
        "label": "默认游戏模式",
        "kind": "select",
        "choices": {
            "survival": "生存",
            "creative": "创造",
            "adventure": "冒险",
            "spectator": "旁观",
        },
    },
    "max-players": {"label": "最大在线人数", "kind": "number", "min": 1, "max": 1000},
    "view-distance": {"label": "视距（区块）", "kind": "number", "min": 3, "max": 32},
    "simulation-distance": {"label": "模拟距离（区块）", "kind": "number", "min": 3, "max": 32},
    "player-idle-timeout": {
        "label": "空闲踢出时间（分钟，0 为关闭）",
        "kind": "number",
        "min": 0,
        "max": 1440,
    },
    "white-list": {"label": "启用白名单", "kind": "boolean"},
    "enforce-whitelist": {"label": "强制执行白名单", "kind": "boolean"},
    "force-gamemode": {"label": "玩家加入时强制默认模式", "kind": "boolean"},
    "allow-flight": {"label": "允许飞行", "kind": "boolean"},
}


class Revision(Payload):
    revision: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ConfigChange(Revision):
    changes: Annotated[dict[str, str], Field(min_length=1, max_length=len(FIELDS))]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def entries(raw: bytes) -> list:
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError("BOM")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            source = raw.decode("latin-1")
        else:
            source = raw.decode("utf-8")
        return list(javaproperties.parse(source))
    except ValueError:
        raise Problem(422, "CONFIG_PARSE_FAILED") from None


def selected(parts: list) -> dict[str, str]:
    return {
        row.key: row.value
        for row in parts
        if isinstance(row, javaproperties.KeyValue) and row.key in FIELDS
    }


def validate_changes(values: dict[str, str], changes: dict[str, str]) -> None:
    for key, value in changes.items():
        if key not in values or key not in FIELDS:
            raise Problem(422, "CONFIG_INVALID_VALUE")
        field = FIELDS[key]
        kind = field["kind"]
        if kind == "text":
            valid = len(value) <= field["max_length"] and (not value or value.isprintable())
        elif kind == "boolean":
            valid = value in ("true", "false")
        elif kind == "select":
            valid = value in field["choices"]
        else:
            valid = (
                bool(re.fullmatch(r"[0-9]{1,4}", value))
                and field["min"] <= int(value) <= field["max"]
            )
        if not valid:
            raise Problem(422, "CONFIG_INVALID_VALUE")


def replace_entries(raw: bytes, parts: list, changes: dict[str, str]) -> bytes:
    # Preserve all unrelated physical lines and their original encoding.
    encoding = "utf-8"
    try:
        raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "latin-1"
    last = {
        part.key: index
        for index, part in enumerate(parts)
        if isinstance(part, javaproperties.KeyValue) and part.key in changes
    }
    by_index = {index: key for key, index in last.items()}
    result = []
    for index, part in enumerate(parts):
        if index not in by_index:
            result.append(part.source)
            continue
        key = by_index[index]
        ending = re.search(r"(?:\r\n|\r|\n)$", part.source)
        result.append(
            javaproperties.join_key_value(key, changes[key]) + (ending[0] if ending else "")
        )
    updated = "".join(result).encode(encoding)
    if len(updated) > LIMIT:
        raise Problem(422, "CONFIG_FILE_TOO_LARGE")
    return updated


def read_file(directory: int, name: str) -> tuple[bytes, int]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Problem(409, "CONFIG_UNAVAILABLE")
        raw = file.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise Problem(422, "CONFIG_FILE_TOO_LARGE")
    return raw, stat.S_IMODE(info.st_mode)


def atomic_write(directory: int, name: str, data: bytes, mode: int) -> None:
    temporary = ".mc-panel-config-" + secrets.token_hex(12)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as file:
            os.fchmod(file.fileno(), mode & 0o777)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def backup_for(directory: int, values: dict[str, str]) -> dict[str, str]:
    try:
        raw, _ = read_file(directory, BACKUP)
        backup = json.loads(raw)
        if not isinstance(backup, dict) or set(backup) != {"before", "after"}:
            return {}
        before, after = backup["before"], backup["after"]
        if (
            not isinstance(before, dict)
            or not isinstance(after, dict)
            or before.keys() != after.keys()
        ):
            return {}
        if any(key not in FIELDS or not isinstance(value, str) for key, value in before.items()):
            return {}
        if any(values.get(key) != value for key, value in after.items()):
            return {}
        return before
    except (OSError, Problem, ValueError):
        return {}


def snapshot(raw: bytes, values: dict[str, str], backup: dict[str, str]) -> dict:
    return {
        "revision": digest(raw),
        "fields": [
            {"key": key, "value": values[key], **spec}
            for key, spec in FIELDS.items()
            if key in values
        ],
        "restore": [
            {"key": key, "before": value, "after": values[key]}
            for key, value in backup.items()
            if key in values and value != values[key]
        ],
    }


def manage_file(state, revision: str | None = None, changes: dict[str, str] | None = None) -> dict:
    if state.profile is None:
        raise Problem(409, "CONFIG_UNAVAILABLE")
    try:
        with open_directory(Path(state.profile.server_dir)) as directory:
            raw, mode = read_file(directory, CONFIG)
            parts = entries(raw)
            values = selected(parts)
            previous = backup_for(directory, values)
            if revision is None:
                return snapshot(raw, values, previous)
            if revision != digest(raw):
                raise Problem(409, "CONFIG_STALE")
            if changes is None:
                if not previous:
                    raise Problem(409, "CONFIG_NO_BACKUP")
                changes = previous
            else:
                validate_changes(values, changes)
            changes = {key: value for key, value in changes.items() if values[key] != value}
            if not changes:
                return snapshot(raw, values, previous)
            before = {key: values[key] for key in changes}
            updated = replace_entries(raw, parts, changes)
            if read_file(directory, CONFIG)[0] != raw:
                raise Problem(409, "CONFIG_STALE")
            history = json.dumps({"before": before, "after": changes}, ensure_ascii=True).encode()
            atomic_write(directory, BACKUP, history, 0o600)
            atomic_write(directory, CONFIG, updated, mode)
            return {**snapshot(updated, values | changes, before), "restart_required": True}
    except OSError:
        raise Problem(409, "CONFIG_UNAVAILABLE") from None


@router.get("")
def get_config(request: Request, user: Admin) -> dict:
    return manage_file(request.app.state)


def apply_change(request: Request, event: str, revision: str, changes=None) -> dict:
    state = request.app.state
    with control_lock(state):
        actor = authorize_action(state, cookie_token(request), event, scope="server.config")
        try:
            result = manage_file(state, revision, changes)
        except Problem:
            operation_audit(state, event, actor, "failed")
            raise
        operation_audit(state, event, actor, "ok")
        return result


@router.patch("", dependencies=[Depends(require_csrf)])
def update_config(payload: ConfigChange, request: Request, user: Admin) -> dict:
    return apply_change(request, "config.update", payload.revision, payload.changes)


@router.post("/restore", dependencies=[Depends(require_csrf)])
def restore_config(payload: Revision, request: Request, user: Admin) -> dict:
    return apply_change(request, "config.restore", payload.revision)
