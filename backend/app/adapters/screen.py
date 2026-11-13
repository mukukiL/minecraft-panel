import re

from app.adapters.base import run_argv
from app.config import Profile
from app.errors import Problem


class ScreenAdapter:
    kind = "screen"
    controls: tuple[str, ...] = ()

    def __init__(self, profile: Profile, run=run_argv) -> None:
        self.profile = profile
        self.run = run

    async def status(self) -> str:
        result = await self.run("/usr/bin/screen", "-ls")
        rows = re.findall(
            r"^\s*\d+\.([^\s]+)\s+[^\n]*\((Attached|Detached|Multi)\)\s*$",
            result.stdout,
            re.MULTILINE,
        )
        count = sum(name == self.profile.session_name for name, _ in rows)
        if count == 1:
            return "session_present"
        if count > 1:
            return "unknown"
        if rows or "No Sockets found" in result.stdout:
            return "session_absent"
        return "unknown"

    async def start(self) -> None:
        raise Problem(409, "SCREEN_CONTROL_UNAVAILABLE")

    async def stop(self) -> None:
        raise Problem(409, "SCREEN_CONTROL_UNAVAILABLE")
