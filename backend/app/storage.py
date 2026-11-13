import hashlib
import os
import re
import secrets
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from app.errors import Problem

JAR_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.jar", re.IGNORECASE | re.ASCII)
if sys.platform == "linux":
    NOFOLLOW = os.O_NOFOLLOW
    NONBLOCK = os.O_NONBLOCK
    DIR_FLAGS = os.O_DIRECTORY | NOFOLLOW | os.O_RDONLY


@contextmanager
def open_directory(path: Path):
    if sys.platform != "linux" or not path.is_absolute() or ".." in path.parts:
        raise Problem(409, "UNSAFE_STORAGE_ROOT")
    fd = os.open("/", DIR_FLAGS)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def tail(root: Path, lines: int) -> list[str]:
    try:
        with open_directory(root / "logs") as folder:
            fd = os.open(
                "latest.log",
                os.O_RDONLY | NOFOLLOW | NONBLOCK,
                dir_fd=folder,
            )
            with os.fdopen(fd, "rb") as log:
                info = os.fstat(log.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise Problem(409, "LOG_UNAVAILABLE")
                start = max(0, info.st_size - 256 * 1024)
                log.seek(start)
                data = log.read(256 * 1024)
    except FileNotFoundError:
        return []
    except OSError:
        raise Problem(409, "LOG_UNAVAILABLE") from None
    rows = data.split(b"\n")
    if start:
        rows = rows[1:]
    if rows and not rows[-1]:
        rows.pop()
    return [row[:4096].decode("utf-8", errors="replace").rstrip("\r") for row in rows[-lines:]]


def validate_jar_name(name: str) -> None:
    if (
        not JAR_NAME.fullmatch(name)
        or ".." in name
        or name.split(".")[0].upper()
        in {
            "CON",
            "AUX",
            "NUL",
            "PRN",
            *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)),
        }
    ):
        raise Problem(422, "INVALID_JAR_NAME")


class Upload:
    def __init__(self, stream: IO[bytes], limit: int):
        self.stream = stream
        self.limit = limit
        self.size = 0
        self.digest = hashlib.sha256()

    def append(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > self.limit:
            raise Problem(413, "UPLOAD_TOO_LARGE")
        self.digest.update(chunk)
        self.stream.write(chunk)

    def finish(self) -> str:
        self.stream.seek(0)
        if self.stream.read(4) != b"PK\x03\x04" or self.size < 52:
            raise Problem(415, "INVALID_JAR")
        # Require a ZIP end record without loading an attacker-controlled central directory.
        self.stream.seek(max(0, self.size - 65_557))
        tail_bytes = self.stream.read(65_557)
        offset = tail_bytes.rfind(b"PK\x05\x06")
        if offset < 0 or len(tail_bytes) - offset < 22:
            raise Problem(415, "INVALID_JAR")
        end = tail_bytes[offset:]
        directory_size = int.from_bytes(end[12:16], "little")
        directory_offset = int.from_bytes(end[16:20], "little")
        if (
            len(end) != 22 + int.from_bytes(end[20:22], "little")
            or end[4:8] != bytes(4)
            or end[8:10] != end[10:12]
            or int.from_bytes(end[10:12], "little") == 0
            or directory_offset + directory_size != self.size - len(end)
        ):
            raise Problem(415, "INVALID_JAR")
        return self.digest.hexdigest()


@contextmanager
def staged_upload(root: Path | None, name: str, limit: int):
    validate_jar_name(name)
    if root is None:
        with tempfile.TemporaryFile("w+b") as temporary:
            yield Upload(temporary, limit), lambda: None
        return
    try:
        with open_directory(root / "mods-disabled") as directory:
            temp = ".upload-" + secrets.token_hex(16)
            fd = os.open(
                temp,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(fd, "w+b") as stream:

                    def publish() -> None:
                        stream.flush()
                        os.fsync(stream.fileno())
                        try:
                            os.link(
                                temp,
                                name,
                                src_dir_fd=directory,
                                dst_dir_fd=directory,
                                follow_symlinks=False,
                            )
                        except FileExistsError:
                            raise Problem(409, "MOD_EXISTS") from None
                        os.fsync(directory)

                    yield Upload(stream, limit), publish
            finally:
                os.unlink(temp, dir_fd=directory)
    except OSError:
        raise Problem(409, "UPLOAD_STORAGE_UNAVAILABLE") from None
