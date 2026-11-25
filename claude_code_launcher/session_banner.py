"""Vollbild-Banner der aktiven Session (Python-Port von banner.sh), läuft außerhalb von curses."""

import os
import select
import shutil
import subprocess
import sys
import termios
import tty

from claude_code_launcher.constants import (
    ANSI_HIDE_CURSOR,
    ANSI_SHOW_CURSOR,
    CLEAR_BINARY,
    ESC_SEQUENCE_READ_SIZE,
    ESC_SEQUENCE_TIMEOUT,
    FIGLET_BINARY,
    KEY_ESC,
    LOLCAT_BINARY,
)


def _banner_top_offset(rows: int, art_height: int) -> int:
    """Leerzeilen über dem Banner für vertikale Zentrierung, nie negativ."""
    return max(0, (rows - art_height) // 2)


def _render_art(name: str, cols: int) -> str:
    """figlet-ASCII-Art des Namens; ohne figlet nur zentrierter Klartext."""
    try:
        result = subprocess.run(
            # "--" verhindert, dass ein Name mit führendem "-" als figlet-Option gilt
            [FIGLET_BINARY, "-c", "-w", str(cols), "--", name],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return name.center(cols)
    return result.stdout.rstrip("\n")


def _print_colored(text: str) -> None:
    """Gibt text via lolcat aus; ohne lolcat ungefärbt."""
    try:
        subprocess.run([LOLCAT_BINARY], input=text, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print(text)


def _has_pending_input(fd: int) -> bool:
    readable, _, _ = select.select([fd], [], [], ESC_SEQUENCE_TIMEOUT)
    return bool(readable)


def _wait_for_escape() -> None:
    """Blockiert bis zu einem einzelnen ESC oder Ctrl+C; Escape-Sequenzen (z. B. Pfeiltasten) werden verworfen."""
    if not sys.stdin.isatty():
        return
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            if os.read(fd, 1) != bytes([KEY_ESC]):
                continue
            if not _has_pending_input(fd):
                return
            while _has_pending_input(fd):
                os.read(fd, ESC_SEQUENCE_READ_SIZE)
    except KeyboardInterrupt:
        # Ctrl+C schließt nur den Banner, nicht den ganzen Launcher
        return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def show_session_banner(name: str) -> None:
    """Zeigt name als zentriertes Vollbild-Banner, bis ESC gedrückt wird."""
    subprocess.run([CLEAR_BINARY], check=False)
    size = shutil.get_terminal_size()
    art = _render_art(name, size.columns)
    try:
        print("\n" * _banner_top_offset(size.lines, art.count("\n") + 1), end="")
        _print_colored(art)
        # Erst nach lolcat, da lolcat den Cursor wieder einblendet
        print(ANSI_HIDE_CURSOR, end="", flush=True)
        _wait_for_escape()
    finally:
        print(ANSI_SHOW_CURSOR, end="", flush=True)
        subprocess.run([CLEAR_BINARY], check=False)
