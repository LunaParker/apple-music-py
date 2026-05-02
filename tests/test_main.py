"""Tests for the ``python -m applemusic`` CLI entry point."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from applemusic.__main__ import main
from applemusic.exceptions import AppleMusicAuthError


class _FakeAuth:
    """Stand-in for AppleMusicAuth that records authenticate() calls."""

    instances: ClassVar[list[_FakeAuth]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.session_dir = kwargs.get("session_dir") or "/fake/path"
        self.force_calls: list[bool] = []
        type(self).instances.append(self)

    def authenticate(self, *, force: bool = False) -> Any:
        self.force_calls.append(force)
        return None


@pytest.fixture(autouse=True)
def reset_fake_auth() -> None:
    _FakeAuth.instances = []


def test_no_args_prints_usage_and_exits_0(capsys) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Usage: applemusic auth" in out


def test_help_flag_prints_usage(capsys) -> None:
    assert main(["--help"]) == 0
    assert "Usage:" in capsys.readouterr().out

    assert main(["-h"]) == 0
    assert "Usage:" in capsys.readouterr().out


def test_unknown_command_returns_2_with_error_on_stderr(capsys) -> None:
    assert main(["nonsense"]) == 2
    captured = capsys.readouterr()
    assert "Unknown command" in captured.err
    assert "Usage:" in captured.err


def test_auth_command_runs_authenticate(monkeypatch, capsys) -> None:
    monkeypatch.setattr("applemusic.__main__.AppleMusicAuth", _FakeAuth)

    assert main(["auth"]) == 0
    assert len(_FakeAuth.instances) == 1
    assert _FakeAuth.instances[0].force_calls == [False]
    assert "Authentication complete" in capsys.readouterr().out


def test_auth_force_flag_is_threaded_through(monkeypatch) -> None:
    monkeypatch.setattr("applemusic.__main__.AppleMusicAuth", _FakeAuth)

    assert main(["auth", "--force"]) == 0
    assert _FakeAuth.instances[0].force_calls == [True]


def test_auth_returns_1_on_auth_error(monkeypatch, capsys) -> None:
    class FailingAuth(_FakeAuth):
        def authenticate(self, *, force: bool = False) -> Any:
            raise AppleMusicAuthError("simulated failure")

    monkeypatch.setattr("applemusic.__main__.AppleMusicAuth", FailingAuth)

    assert main(["auth"]) == 1
    assert "simulated failure" in capsys.readouterr().err


def test_auth_returns_130_on_keyboard_interrupt(monkeypatch, capsys) -> None:
    class CancelledAuth(_FakeAuth):
        def authenticate(self, *, force: bool = False) -> Any:
            raise KeyboardInterrupt

    monkeypatch.setattr("applemusic.__main__.AppleMusicAuth", CancelledAuth)

    assert main(["auth"]) == 130
    assert "cancelled" in capsys.readouterr().err.lower()
