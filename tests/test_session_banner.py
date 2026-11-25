import subprocess
import sys

from claude_code_launcher import session_banner
from claude_code_launcher.session_banner import _banner_top_offset, _render_art


def test_banner_top_offset_centers_vertically():
    assert _banner_top_offset(24, 6) == 9


def test_banner_top_offset_never_negative():
    assert _banner_top_offset(4, 10) == 0


def test_render_art_passes_name_after_option_terminator(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="art\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _render_art("-v", 80)
    assert calls[0][-2:] == ["--", "-v"]


class _FakeStdin:
    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty

    def fileno(self) -> int:
        return 0


def _interrupting_read(fd: int, size: int) -> bytes:
    raise KeyboardInterrupt


def test_wait_for_escape_returns_without_tty(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin(is_tty=False))
    assert session_banner._wait_for_escape() is None


def test_wait_for_escape_treats_ctrl_c_as_escape(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin(is_tty=True))
    monkeypatch.setattr(session_banner.termios, "tcgetattr", lambda fd: [])
    monkeypatch.setattr(session_banner.termios, "tcsetattr", lambda fd, when, attrs: None)
    monkeypatch.setattr(session_banner.tty, "setcbreak", lambda fd: None)
    monkeypatch.setattr(session_banner.os, "read", _interrupting_read)
    assert session_banner._wait_for_escape() is None
