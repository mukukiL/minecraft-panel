import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.adapters.base import Result
from app.adapters.screen import ScreenAdapter
from app.adapters.tmux import TmuxAdapter
from app.config import Profile
from app.errors import Problem


def profile(**updates):
    return Profile(
        **(
            {
                "adapter": "tmux",
                "session_name": "fixture",
                "server_dir": "/opt/test game",
                "launch_entrypoint": "/usr/local/bin/fake-server",
                "tmux_socket": "/run/test.sock",
                "game_port": 25565,
                "allow_tmux_stop": True,
            }
            | updates
        )
    )


def test_bad_target():
    with pytest.raises(ValidationError):
        profile(session_name="x;stop")
    with pytest.raises(ValidationError):
        profile(server_dir="/opt/../etc")


def test_tmux_fixed_argv():
    run = AsyncMock(side_effect=[Result(0, "123|keeper\n"), Result(0, "")])
    adapter = TmuxAdapter(profile(), run, lambda _: True, lambda _: False)
    asyncio.run(adapter.start())
    assert run.await_args.args == (
        "/usr/bin/tmux",
        "-N",
        "-S",
        "/run/test.sock",
        "new-session",
        "-d",
        "-s",
        "fixture",
        "-n",
        "minecraft",
        "-c",
        "/opt/test game",
        "--",
        "/usr/bin/env",
        "--",
        "/usr/local/bin/fake-server",
    )


@pytest.mark.parametrize(
    ("result", "separate", "busy", "code"),
    [
        (Result(1, ""), True, False, "TMUX_SERVER_UNAVAILABLE"),
        (Result(0, "123|keeper\n"), False, False, "TMUX_CGROUP_UNVERIFIED"),
        (Result(0, "123|keeper\n"), True, True, "GAME_PORT_BUSY"),
    ],
)
def test_tmux_start_preconditions(result, separate, busy, code):
    run = AsyncMock(return_value=result)
    with pytest.raises(Problem, match=code):
        asyncio.run(TmuxAdapter(profile(), run, lambda _: separate, lambda _: busy).start())
    assert run.await_count == 1


def test_tmux_existing_session_cannot_be_started_again():
    run = AsyncMock(
        side_effect=[
            Result(0, "123|fixture\n"),
            Result(0, "%3|minecraft|java|/opt/test game|0|0|456\n"),
        ]
    )
    with pytest.raises(Problem, match="TMUX_SESSION_EXISTS"):
        asyncio.run(TmuxAdapter(profile(), run).start())
    assert run.await_count == 2


@pytest.mark.parametrize("command", ["bash", "java"])
def test_tmux_stop_checks_foreground(command):
    run = AsyncMock(
        side_effect=[
            Result(0, "123|fixture\n"),
            Result(0, f"%3|minecraft|{command}|/opt/test game|0|0|456\n"),
            Result(0, ""),
        ]
    )
    adapter = TmuxAdapter(profile(), run, lambda _: True, verify_java=lambda _: True)
    if command == "java":
        asyncio.run(adapter.stop())
        assert run.await_args.args[-2] == "send-keys -t %3 -l -- stop ; send-keys -t %3 Enter"
    else:
        with pytest.raises(Problem, match="TMUX_PANE_UNVERIFIED"):
            asyncio.run(adapter.stop())
        assert run.await_count == 2


def test_screen_exact_target_and_no_blind_input():
    run = AsyncMock(return_value=Result(1, "  4.fixture-other (Detached)\n"))
    adapter = ScreenAdapter(profile(adapter="screen"), run)
    assert asyncio.run(adapter.status()) == "session_absent"
    run.return_value = Result(1, "  4.fixture (Detached)\n")
    assert asyncio.run(adapter.status()) == "session_present"
    with pytest.raises(Problem, match="SCREEN_CONTROL_UNAVAILABLE"):
        asyncio.run(adapter.stop())
    assert all(call.args == ("/usr/bin/screen", "-ls") for call in run.await_args_list)


@pytest.mark.parametrize(
    ("owned", "busy", "state"),
    [(True, True, "running"), (False, True, "port_conflict"), (False, False, "starting")],
)
def test_tmux_port_must_belong_to_java(owned, busy, state):
    run = AsyncMock(
        side_effect=[
            Result(0, "123|fixture\n"),
            Result(0, "%3|minecraft|java|/opt/test game|0|0|456\n"),
        ]
    )
    adapter = TmuxAdapter(
        profile(),
        run,
        port_busy=lambda _: busy,
        verify_java=lambda _: True,
        listening=lambda pid, port: owned and (pid, port) == (456, 25565),
    )
    assert asyncio.run(adapter.status()) == state
