"""Clipboard- und Login-Shell-PATH-Helfer ohne UI-Bezug."""

import base64
import os
import subprocess
import sys

from .constants import (
    CLIPBOARD_BINARY,
    CLIPBOARD_COPY_TIMEOUT,
    DEFAULT_SHELL,
    LOGIN_SHELL_PATH_PROBE_TIMEOUT,
    OSC52_CLIPBOARD_TEMPLATE,
    PATH_PROBE_END_MARKER,
    PATH_PROBE_START_MARKER,
)


def _copy_to_clipboard(text: str) -> bool:
    """Kopiert text in die Zwischenablage: pbcopy auf macOS, OSC 52 sonst."""
    if sys.platform == "darwin":
        return _copy_via_pbcopy(text)
    return _copy_via_osc52(text)


def _copy_via_pbcopy(text: str) -> bool:
    """Kopiert text per pbcopy in die macOS-Zwischenablage."""
    try:
        subprocess.run(
            [CLIPBOARD_BINARY],
            input=text,
            text=True,
            timeout=CLIPBOARD_COPY_TIMEOUT,
            check=True,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _copy_via_osc52(text: str) -> bool:
    """Schreibt eine OSC-52-Sequenz auf stdout (Terminal-Zwischenablage über SSH, ohne Display-Server)."""
    encoded = base64.b64encode(text.encode()).decode()
    try:
        sys.stdout.write(OSC52_CLIPBOARD_TEMPLATE.format(encoded))
        sys.stdout.flush()
        return True
    except OSError:
        return False


def _load_login_shell_path() -> str | None:
    """Liest den PATH aus einer interaktiven Login-Shell.

    Wird der Launcher außerhalb eines Login-Terminals gestartet, erbt er einen
    reduzierten PATH und Subprozesse finden Befehle wie `code`/`claude` nicht.
    Interaktiv + Login, weil PATH-Setup sowohl in ~/.zprofile (Login) als auch
    ~/.zshrc (nur interaktiv) liegen kann. Marker isolieren den PATH von
    stdout-Noise der rc-Dateien.
    """
    shell = os.environ.get("SHELL", DEFAULT_SHELL)
    probe_command = (
        f'printf "{PATH_PROBE_START_MARKER}%s{PATH_PROBE_END_MARKER}" "$PATH"'
    )
    try:
        result = subprocess.run(
            [shell, "-l", "-i", "-c", probe_command],
            capture_output=True,
            text=True,
            timeout=LOGIN_SHELL_PATH_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    _, start_found, rest = result.stdout.partition(PATH_PROBE_START_MARKER)
    path, end_found, _ = rest.partition(PATH_PROBE_END_MARKER)
    if not start_found or not end_found or not path:
        return None
    return path
