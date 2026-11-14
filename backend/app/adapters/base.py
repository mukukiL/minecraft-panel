import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.errors import Problem


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str
    stderr: str = ""


async def run_argv(*argv: str, input_data: bytes | None = None) -> Result:
    try:
        child = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except OSError:
        raise Problem(503, "ADAPTER_UNAVAILABLE") from None
    try:
        stdout, stderr = await asyncio.wait_for(child.communicate(input_data), timeout=5)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if child.returncode is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
        await child.wait()
        if isinstance(exc, TimeoutError):
            raise Problem(504, "ADAPTER_TIMEOUT") from None
        raise
    return Result(
        child.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    )


class Adapter(Protocol):
    kind: str
    controls: tuple[str, ...]

    async def status(self) -> str: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
