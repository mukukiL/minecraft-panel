import os
import re
import stat
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
NAME = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$"


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter: Literal["tmux", "screen"]
    session_name: str = Field(pattern=NAME)
    window_name: str = Field(default="minecraft", pattern=NAME)
    server_dir: PurePosixPath
    launch_entrypoint: PurePosixPath
    tmux_socket: PurePosixPath | None = None
    game_port: int = Field(ge=1, le=65535)
    stop_timeout: int = Field(default=90, ge=1, le=120)
    start_timeout: int = Field(default=90, ge=1, le=120)
    allow_tmux_stop: bool = False
    allow_tmux_console: bool = False

    @model_validator(mode="after")
    def validate_paths(self) -> "Profile":
        for path in (self.server_dir, self.launch_entrypoint, self.tmux_socket):
            if path is not None and (
                not path.is_absolute()
                or ".." in path.parts
                or not re.fullmatch(r"/[a-zA-Z0-9_./ -]+", str(path))
            ):
                raise ValueError("profile paths must be absolute Linux paths without shell syntax")
        if self.adapter == "tmux" and self.tmux_socket is None:
            raise ValueError("tmux requires an explicit socket path")
        return self


class Settings(BaseModel):
    env: Literal["development", "production"] = "development"
    public_origin: str = "http://localhost:5173"
    db_path: Path = ROOT / "var" / "panel.db"
    profile_path: Path | None = None
    session_idle: int = Field(default=28_800, ge=1)
    session_ttl: int = Field(default=604_800, ge=1)
    upload_limit: int = Field(default=32 * 1024**2, ge=1024, le=256 * 1024**2)

    @model_validator(mode="after")
    def validate_origin(self) -> "Settings":
        origin = urlsplit(self.public_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username is not None
            or origin.path
            or origin.query
            or origin.fragment
            or self.public_origin != f"{origin.scheme}://{origin.netloc}"
        ):
            raise ValueError("public origin must contain only scheme and authority")
        _ = origin.port
        if self.env == "production" and origin.scheme != "https":
            raise ValueError("production requires an HTTPS public origin")
        if origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("HTTP development is restricted to loopback origins")
        if self.session_idle > self.session_ttl:
            raise ValueError("idle timeout cannot exceed absolute session lifetime")
        return self

    @property
    def secure_cookie(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def cookie_name(self) -> str:
        return "__Host-mcpanel_session" if self.secure_cookie else "mcpanel_dev_session"


def load_settings() -> Settings:
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    return Settings.model_validate(
        {
            name: values[key]
            for name in Settings.model_fields
            if (key := f"MC_PANEL_{name.upper()}") in values and values[key] not in (None, "")
        }
    )


def require_root_file(path: Path) -> None:
    # Resolve is used for config ownership checks, never for user-controlled uploads.
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("trusted configuration and launcher require canonical paths")
    for node in (path, *path.parents):
        info = node.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or os.access(node, os.W_OK):
            raise ValueError("trusted configuration and launcher must be root-controlled")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("expected a regular file")


def load_profile(settings: Settings) -> Profile | None:
    if settings.profile_path is None:
        return None
    if sys.platform != "linux" or not Path("/proc/self/cgroup").is_file():
        raise ValueError("live profiles require Linux")
    if os.geteuid() == 0:
        raise ValueError("live profiles require a non-root panel process")
    if settings.env == "production":
        require_root_file(settings.profile_path)
    with settings.profile_path.open("rb") as config:
        profile = Profile.model_validate(tomllib.load(config)["profile"])
    server_dir = Path(profile.server_dir)
    launcher = Path(profile.launch_entrypoint)
    if settings.env == "production":
        require_root_file(launcher)
    if (
        server_dir.resolve(strict=True) != server_dir
        or not server_dir.is_dir()
        or not launcher.is_file()
        or not os.access(launcher, os.X_OK)
    ):
        raise ValueError("invalid server directory or launcher")
    return profile
