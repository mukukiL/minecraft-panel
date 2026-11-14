import os
import re
import secrets
import socket
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.adapters.base import Result, run_argv
from app.config import Profile
from app.errors import Problem


@dataclass(frozen=True)
class Pane:
    id: str
    pid: int
    command: str
    cwd: str
    dead: bool


def isolated_server(pid: int) -> bool:
    try:
        panel = Path("/proc/self/cgroup").read_text().splitlines()
        server = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
    except OSError:
        return False
    # Shared root cgroups do not establish separation. Refuse descendants too.
    panel_paths = dict(line.rsplit(":", 1) for line in panel)
    server_paths = dict(line.rsplit(":", 1) for line in server)
    return any(
        name in panel_paths
        and path != panel_paths[name]
        and not path.startswith(panel_paths[name].rstrip("/") + "/")
        for name, path in server_paths.items()
        if name == "0:" or name.endswith(":name=systemd")
    )


def port_in_use(port: int) -> bool:
    # Binding without listening detects wildcard and local specific-address listeners.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("0.0.0.0", port))
        except OSError:
            return True
    if socket.has_ipv6:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                probe.bind(("::", port))
            except OSError:
                return True
    return False


def java_process(pane: Pane) -> bool:
    proc = Path(f"/proc/{pane.pid}")
    try:
        return (
            proc.stat().st_uid == os.geteuid()
            and (proc / "exe").readlink().name == "java"
            and (proc / "cwd").readlink() == Path(pane.cwd)
        )
    except OSError:
        return False


def owns_listener(pid: int, port: int) -> bool:
    proc = Path(f"/proc/{pid}")
    try:
        sockets = set()
        for fd in (proc / "fd").iterdir():
            try:
                sockets.add(fd.readlink().name)
            except FileNotFoundError:
                continue
        for table in ("tcp", "tcp6"):
            for line in (proc / "net" / table).read_text().splitlines()[1:]:
                fields = line.split()
                if (
                    len(fields) >= 10
                    and fields[3] == "0A"
                    and fields[1].endswith(f":{port:04X}")
                    and f"socket:[{fields[9]}]" in sockets
                ):
                    return True
    except OSError:
        return False
    return False


class TmuxAdapter:
    kind = "tmux"

    def __init__(
        self,
        profile: Profile,
        run=run_argv,
        separated: Callable[[int], bool] = isolated_server,
        port_busy: Callable[[int], bool] = port_in_use,
        verify_java: Callable[[Pane], bool] = java_process,
        listening: Callable[[int, int], bool] = owns_listener,
    ) -> None:
        self.profile = profile
        self.run = run
        self.separated = separated
        self.port_busy = port_busy
        self.verify_java = verify_java
        self.listening = listening
        self.controls = ("start", "stop", "restart") if profile.allow_tmux_stop else ("start",)
        self.console_available = profile.allow_tmux_console

    async def command(self, *args: str, input_data: bytes | None = None) -> Result:
        # -N is essential. If the external tmux server exits between calls,
        # new-session must fail instead of creating a server in the panel cgroup.
        argv = ("/usr/bin/tmux", "-N", "-S", str(self.profile.tmux_socket), *args)
        if input_data is not None:
            return await self.run(*argv, input_data=input_data)
        return await self.run(*argv)

    async def snapshot(self) -> tuple[int, list[str], Pane | None]:
        result = await self.command("list-sessions", "-F", "#{pid}|#{session_name}")
        rows = [line.split("|", 1) for line in result.stdout.splitlines()]
        if (
            result.code
            or not rows
            or any(len(row) != 2 or not re.fullmatch(r"[1-9][0-9]{0,9}", row[0]) for row in rows)
        ):
            raise Problem(503, "TMUX_SERVER_UNAVAILABLE")
        pid = int(rows[0][0])
        sessions = [row[1] for row in rows]
        if self.profile.session_name not in sessions:
            return pid, sessions, None

        result = await self.command(
            "list-panes",
            "-s",
            "-t",
            "=" + self.profile.session_name,
            "-F",
            "#{pane_id}|#{window_name}|#{pane_current_command}|#{pane_current_path}"
            "|#{pane_dead}|#{pane_in_mode}|#{pane_pid}",
        )
        lines = result.stdout.splitlines()
        if result.code or len(lines) != 1:
            raise Problem(409, "TMUX_PANE_UNVERIFIED")
        fields = lines[0].split("|")
        if (
            len(fields) != 7
            or not re.fullmatch(r"%[0-9]+", fields[0])
            or fields[1] != self.profile.window_name
            or fields[4] not in ("0", "1")
            or fields[5] != "0"
            or not re.fullmatch(r"[1-9][0-9]{0,9}", fields[6])
        ):
            raise Problem(409, "TMUX_PANE_UNVERIFIED")
        return (
            pid,
            sessions,
            Pane(fields[0], int(fields[6]), fields[2], fields[3], fields[4] == "1"),
        )

    def is_java(self, pane: Pane) -> bool:
        return (
            not pane.dead
            and pane.command == "java"
            and pane.cwd == str(self.profile.server_dir)
            and self.verify_java(pane)
        )

    async def status(self) -> str:
        try:
            _, _, pane = await self.snapshot()
        except Problem:
            return "unknown"
        if pane is None:
            return "port_conflict" if self.port_busy(self.profile.game_port) else "stopped"
        if self.is_java(pane):
            if self.listening(pane.pid, self.profile.game_port):
                return "running"
            return "port_conflict" if self.port_busy(self.profile.game_port) else "starting"
        return "unknown"

    async def start(self) -> None:
        pid, _, pane = await self.snapshot()
        if pane is not None:
            raise Problem(409, "TMUX_SESSION_EXISTS")
        if not self.separated(pid):
            raise Problem(409, "TMUX_CGROUP_UNVERIFIED")
        if self.port_busy(self.profile.game_port):
            raise Problem(409, "GAME_PORT_BUSY")
        result = await self.command(
            "new-session",
            "-d",
            "-s",
            self.profile.session_name,
            "-n",
            self.profile.window_name,
            "-c",
            str(self.profile.server_dir),
            "--",
            "/usr/bin/env",
            "--",
            str(self.profile.launch_entrypoint),
        )
        if result.code:
            raise Problem(409, "TMUX_START_FAILED")

    async def stop(self) -> None:
        if not self.profile.allow_tmux_stop:
            raise Problem(409, "TMUX_STOP_DISABLED")
        pane = await self.command_pane()
        result = await self.send_if_java(
            pane, f"send-keys -t {pane.id} -l -- stop ; send-keys -t {pane.id} Enter"
        )
        if result.code or result.stdout.strip() == "STOP_REFUSED":
            raise Problem(409, "TMUX_STOP_FAILED")

    async def command_pane(self) -> Pane:
        pid, _, pane = await self.snapshot()
        if pane is None or not self.is_java(pane) or not self.separated(pid):
            raise Problem(409, "TMUX_PANE_UNVERIFIED")
        return pane

    async def send_if_java(self, pane: Pane, commands: str) -> Result:
        # Check the foreground again inside tmux immediately before queuing the keys.
        cwd = str(self.profile.server_dir)
        check = (
            "#{&&:#{==:#{pane_current_command},java},"
            "#{&&:#{==:#{pane_dead},0},"
            "#{&&:#{==:#{pane_in_mode},0},"
            f"#{{&&:#{{==:#{{pane_current_path}},{cwd}}},"
            f"#{{==:#{{pane_pid}},{pane.pid}}}"
            "}}}}"
        )
        return await self.command(
            "if-shell",
            "-F",
            "-t",
            pane.id,
            check,
            commands,
            "display-message -p STOP_REFUSED",
        )

    async def console(self, command: str) -> None:
        if not self.console_available:
            raise Problem(409, "CONSOLE_UNAVAILABLE")
        pane = await self.command_pane()
        if not self.listening(pane.pid, self.profile.game_port):
            raise Problem(409, "SERVER_NOT_RUNNING")
        buffer = "mc-panel-" + secrets.token_hex(16)
        # The command goes through stdin as data, including quotes and semicolons.
        try:
            loaded = await self.command(
                "load-buffer", "-b", buffer, "-", input_data=command.encode()
            )
            if loaded.code:
                raise Problem(409, "CONSOLE_SEND_FAILED")
            result = await self.send_if_java(
                pane, f"paste-buffer -d -r -b {buffer} -t {pane.id} ; send-keys -t {pane.id} Enter"
            )
            if result.code or result.stdout.strip() == "STOP_REFUSED":
                raise Problem(409, "CONSOLE_SEND_FAILED")
        finally:
            with suppress(Problem):
                await self.command("delete-buffer", "-b", buffer)
