import subprocess
from unittest.mock import patch

from claude_code_launcher.constants import PROMPT_IS_DARK_SCRIPT_RELATIVE_PATH
from claude_code_launcher.system_helpers import _detect_linux_terminal_theme


def test_detect_linux_terminal_theme_returns_none_when_script_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _detect_linux_terminal_theme() is None


def _create_script(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    script_path = tmp_path / PROMPT_IS_DARK_SCRIPT_RELATIVE_PATH
    script_path.parent.mkdir(parents=True)
    script_path.write_text("_prompt_is_dark() { return 0; }\n")


def test_detect_linux_terminal_theme_returns_dark_on_exit_code_zero(
    tmp_path, monkeypatch
):
    _create_script(tmp_path, monkeypatch)
    with patch("claude_code_launcher.system_helpers.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert _detect_linux_terminal_theme() == "dark"


def test_detect_linux_terminal_theme_returns_light_on_exit_code_one(
    tmp_path, monkeypatch
):
    _create_script(tmp_path, monkeypatch)
    with patch("claude_code_launcher.system_helpers.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        assert _detect_linux_terminal_theme() == "light"


def test_detect_linux_terminal_theme_returns_none_on_unexpected_exit_code(
    tmp_path, monkeypatch
):
    _create_script(tmp_path, monkeypatch)
    with patch("claude_code_launcher.system_helpers.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 2
        assert _detect_linux_terminal_theme() is None


def test_detect_linux_terminal_theme_returns_none_on_missing_zsh_binary(
    tmp_path, monkeypatch
):
    _create_script(tmp_path, monkeypatch)
    with patch(
        "claude_code_launcher.system_helpers.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert _detect_linux_terminal_theme() is None


def test_detect_linux_terminal_theme_returns_none_on_timeout(tmp_path, monkeypatch):
    _create_script(tmp_path, monkeypatch)
    with patch(
        "claude_code_launcher.system_helpers.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="zsh", timeout=6),
    ):
        assert _detect_linux_terminal_theme() is None
