#!/usr/bin/env python3
"""Claude Code Launcher - Session Management Tool für Workspace"""

VERSION = "vYYMMDDhhmm"

import fnmatch
import json
import os
import shutil
import sys
import argparse
import tomllib
import curses
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Literal, overload
from collections.abc import Callable

# --- Curses Farb-Paar IDs ---
COLOR_PAIR_ORANGE = 1
COLOR_PAIR_GRAY = 2
COLOR_PAIR_GREEN = 3
COLOR_PAIR_YELLOW = 4
COLOR_PAIR_WHITE = 5

# --- xterm256-Farben mit 8-Color-Fallback ---
MIN_COLORS_FOR_XTERM256 = 256
CLAUDE_ORANGE_XTERM256_COLOR = 166  # Titel/Branding (~#DA7756)
CLAUDE_ORANGE_FALLBACK_COLOR = curses.COLOR_YELLOW
MENU_HIGHLIGHT_XTERM256_COLOR = 226  # aktive Auswahl
MENU_HIGHLIGHT_FALLBACK_COLOR = curses.COLOR_YELLOW
HINT_GRAY_XTERM256_COLOR = 245  # Status/Hints
HINT_GRAY_FALLBACK_COLOR = curses.COLOR_WHITE

# --- Key Codes ---
KEY_TAB = 9
KEY_ESC = 27
KEY_BACKSPACE_DEL = 127
KEY_SPACE = 32
KEY_PRINTABLE_MAX = 126

# XTerm Any-Event-Mouse-Tracking manuell schalten, da curses.mousemask() mit
# REPORT_MOUSE_POSITION dies bei Apples mitgelieferter libncurses (5.4) nicht
# zuverlässig ans Terminal übersetzt (keine Bewegungs-Events ohne Klick).
XTERM_ENABLE_MOUSE_MOTION_TRACKING = "\x1b[?1003h"
XTERM_DISABLE_MOUSE_MOTION_TRACKING = "\x1b[?1003l"

# --- UI Layout ---
MENU_TITLE_ROW = 1
MENU_SEPARATOR_ROW = 2
MENU_START_ROW = 4
UI_PADDING_X = 2
MENU_RIGHT_COL_BUFFER = 10
MENU_COLUMN_GAP_X = 4          # Abstand zwischen Menüspalte 1 und Spalte 2
MENU_ITEM_PREFIX_WIDTH = 2     # Breite von "> " bzw. "  " Präfix vor jedem Label
USAGE_STATS_COL_WIDTH = 26     # Reservierte Breite für die Claude-Nutzungsstatistik-Spalte ganz rechts
USAGE_STATS_MIN_GAP = MENU_COLUMN_GAP_X

# Spalten-Zuordnung für curses_menu(); muss mit Action-Keys aus LauncherApp.get_menu_items() übereinstimmen.
WORKFLOW_ACTIONS = frozenset({"plan", "start", "export", "import"})

# --- Footer / Cheatsheet ---
RECENT_SHORTCUTS_MAX_ENTRIES = 6
# Ein-Buchstaben-Hotkeys aus curses_menu() mit Anzeigetext, gemeinsame Quelle für
# Footer (dynamischer Ausschnitt) und Cheatsheet ([h], vollständige Liste).
SHORTCUT_LABELS: dict[str, str] = {
    "r": "Refresh",
    "s": "Sitzung starten",
    "t": "Shell",
    "e": "Quick Export",
    "i": "Quick Import",
    "v": "VS Code",
    "p": "Plan schreiben",
    "x": "Nach Export zurücksetzen",
    "o": "Überschreiben bestätigen",
    "h": "Hilfe",
    "q": "Beenden",
}
# Menü-Actions (LauncherApp.handle_action()), deren Nutzung in recent_shortcuts getrackt wird.
ACTION_TO_SHORTCUT: dict[str, str] = {
    "start": "s",
    "shell": "t",
    "plan": "p",
    "export_first": "e",
    "import_first": "i",
    "open_import_source": "v",
}

# --- Dateigrößen ---
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024

# --- Plan-Idle-Timer ---
MILLISECONDS_PER_SECOND = 1000
DEFAULT_PLAN_IDLE_TIMER_DURATION = 10

# --- rsync (Folder-Mode Export/Import) ---
RSYNC_BINARY = "rsync"
RSYNC_BASE_ARGS = ["-a", "--delete"]
RSYNC_DELETE_EXCLUDED_ARG = "--delete-excluded"

# --- VS Code CLI (Importquelle öffnen) ---
VSCODE_BINARY = "code"

# --- Shell / Login-Shell-PATH ---
DEFAULT_SHELL = "/bin/zsh"
LOGIN_SHELL_PATH_PROBE_TIMEOUT = 5
PATH_PROBE_START_MARKER = "__PATH_START__"
PATH_PROBE_END_MARKER = "__PATH_END__"

# --- openusage CLI (Claude-Nutzungsstatistik) ---
OPENUSAGE_BINARY = "openusage"
OPENUSAGE_PROVIDER = "claude"
OPENUSAGE_FETCH_TIMEOUT = 3
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440

# --- Einrückung für Listen-Einträge (UI_PADDING_X + "> " Präfix) ---
ITEM_INDENT_X = UI_PADDING_X + 2  # = 4


def _resolve_xterm256_color(xterm256_color: int, fallback_color: int) -> int:
    """Wählt xterm256_color bei 256-Color-Terminal-Support, sonst fallback_color."""
    return xterm256_color if curses.COLORS >= MIN_COLORS_FOR_XTERM256 else fallback_color


def _init_curses_colors(stdscr: "curses.window") -> None:
    """Initialisiert alle Curses Farb-Paare und setzt Cursor einmalig.

    Args:
        stdscr: Das Curses Hauptfenster.
    """
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(
        COLOR_PAIR_ORANGE,
        _resolve_xterm256_color(CLAUDE_ORANGE_XTERM256_COLOR, CLAUDE_ORANGE_FALLBACK_COLOR),
        -1,
    )
    curses.init_pair(
        COLOR_PAIR_GRAY,
        _resolve_xterm256_color(HINT_GRAY_XTERM256_COLOR, HINT_GRAY_FALLBACK_COLOR),
        -1,
    )
    curses.init_pair(COLOR_PAIR_GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(
        COLOR_PAIR_YELLOW,
        _resolve_xterm256_color(MENU_HIGHLIGHT_XTERM256_COLOR, MENU_HIGHLIGHT_FALLBACK_COLOR),
        -1,
    )
    curses.init_pair(COLOR_PAIR_WHITE, curses.COLOR_WHITE, -1)


def _is_up_key(key: int) -> bool:
    """Prüft ob key eine Aufwärts-Navigation auslöst.

    Args:
        key: Curses-Tastencode.

    Returns:
        True für KEY_UP oder Shift+Tab.
    """
    return key in (curses.KEY_UP, curses.KEY_BTAB)


def _is_down_key(key: int, include_tab: bool = True) -> bool:
    """Prüft ob key eine Abwärts-Navigation auslöst.

    Args:
        key: Curses-Tastencode.
        include_tab: Ob Tab als Abwärts-Taste gilt (Standard: True).

    Returns:
        True für KEY_DOWN oder (wenn include_tab) Tab.
    """
    return key == curses.KEY_DOWN or (include_tab and key == KEY_TAB)


def _is_left_key(key: int) -> bool:
    """Prüft ob key eine Links-Navigation auslöst.

    Args:
        key: Curses-Tastencode.

    Returns:
        True für KEY_LEFT.
    """
    return key == curses.KEY_LEFT


def _is_right_key(key: int) -> bool:
    """Prüft ob key eine Rechts-Navigation auslöst.

    Args:
        key: Curses-Tastencode.

    Returns:
        True für KEY_RIGHT.
    """
    return key == curses.KEY_RIGHT


def _split_menu_columns(
    menu_items: list[tuple[str, str]],
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Teilt Menü-Items anhand WORKFLOW_ACTIONS in zwei Spalten auf.

    Args:
        menu_items: Liste von (action_key, label) Tuples in Original-Reihenfolge.

    Returns:
        (col1, col2): je eine Liste von (original_index, label) Tuples;
        original_index verweist auf die Position in menu_items.
    """
    col1: list[tuple[int, str]] = []
    col2: list[tuple[int, str]] = []
    for i, (action, label) in enumerate(menu_items):
        target = col1 if action in WORKFLOW_ACTIONS else col2
        target.append((i, label))
    return col1, col2


def _swap_menu_column(
    current: int,
    col1: list[tuple[int, str]],
    col2: list[tuple[int, str]],
) -> int:
    """Wechselt current in die jeweils andere Spalte, möglichst gleiche Zeile.

    Args:
        current: Aktueller Original-Index in menu_items.
        col1: Erste Spalte als (original_index, label) Tuples.
        col2: Zweite Spalte als (original_index, label) Tuples.

    Returns:
        Original-Index des Ziel-Eintrags; unverändertes current falls
        die Zielspalte leer ist.
    """
    for row, (original_index, _label) in enumerate(col1):
        if original_index == current and col2:
            return col2[min(row, len(col2) - 1)][0]
    for row, (original_index, _label) in enumerate(col2):
        if original_index == current and col1:
            return col1[min(row, len(col1) - 1)][0]
    return current


def _render_menu_column(
    stdscr: "curses.window",
    column: list[tuple[int, str]],
    current: int,
    x: int,
    height: int,
) -> None:
    """Rendert eine Menüspalte an X-Position x, highlightet den aktiven Eintrag.

    Args:
        stdscr: Das Curses Hauptfenster.
        column: (original_index, label) Tuples dieser Spalte.
        current: Global aktuell gewählter Original-Index (für Highlight).
        x: X-Startposition der Spalte.
        height: Terminalhöhe (für Sichtbarkeits-Check).
    """
    for row, (original_index, label) in enumerate(column):
        y = MENU_START_ROW + row
        if y >= height - 2:
            break
        if original_index == current:
            stdscr.addstr(
                y, x, f"> {label}", curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD
            )
        else:
            stdscr.addstr(y, x, f"  {label}")


def _menu_column_hit_index(
    column: list[tuple[int, str]],
    x: int,
    label_width: int,
    mouse_y: int,
    mouse_x: int,
    height: int,
) -> int | None:
    """Prüft ob (mouse_y, mouse_x) einen Eintrag dieser Spalte trifft.

    Spiegelt die Geometrie von _render_menu_column(): gleiche Y-Formel,
    gleiche Sichtbarkeitsgrenze, X-Bereich = Präfix- + Label-Breite.

    Args:
        column: (original_index, label) Tuples dieser Spalte.
        x: X-Startposition der Spalte (wie an _render_menu_column übergeben).
        label_width: Breite des längsten Labels dieser Spalte.
        mouse_y: Bildschirm-Y-Position des Mausereignisses.
        mouse_x: Bildschirm-X-Position des Mausereignisses.
        height: Terminalhöhe (für Sichtbarkeits-Check).

    Returns:
        original_index des getroffenen Eintrags, oder None.
    """
    row = mouse_y - MENU_START_ROW
    if row < 0 or row >= len(column):
        return None
    if MENU_START_ROW + row >= height - 2:
        return None
    item_width = MENU_ITEM_PREFIX_WIDTH + label_width
    if not (x <= mouse_x < x + item_width):
        return None
    return column[row][0]


def _menu_item_at_position(
    col1: list[tuple[int, str]],
    col2: list[tuple[int, str]],
    col1_x: int,
    col2_x: int,
    col1_label_width: int,
    col2_label_width: int,
    mouse_y: int,
    mouse_x: int,
    height: int,
) -> int | None:
    """Ermittelt den original_index des Menüeintrags unter dem Mauszeiger.

    Args:
        col1: Erste Menüspalte als (original_index, label) Tuples.
        col2: Zweite Menüspalte als (original_index, label) Tuples.
        col1_x: X-Startposition von Spalte 1.
        col2_x: X-Startposition von Spalte 2.
        col1_label_width: Breite des längsten Labels in Spalte 1.
        col2_label_width: Breite des längsten Labels in Spalte 2.
        mouse_y: Bildschirm-Y-Position des Mausereignisses.
        mouse_x: Bildschirm-X-Position des Mausereignisses.
        height: Terminalhöhe (für Sichtbarkeits-Check).

    Returns:
        original_index des getroffenen Eintrags, oder None falls kein Treffer.
    """
    hit = _menu_column_hit_index(col1, col1_x, col1_label_width, mouse_y, mouse_x, height)
    if hit is not None:
        return hit
    return _menu_column_hit_index(col2, col2_x, col2_label_width, mouse_y, mouse_x, height)


def _select_item_at_position(
    items: list[tuple[str, str]], mouse_y: int, mouse_x: int, height: int
) -> int | None:
    """Ermittelt den Listenindex unter dem Mauszeiger in curses_select().

    Spiegelt die Render-Geometrie: y = MENU_START_ROW + i, Sichtbarkeitsgrenze
    height - 3, keine Scroll-Offset (im Gegensatz zu curses_browse()).

    Args:
        items: Liste von (value, label) Tuples.
        mouse_y: Bildschirm-Y-Position des Mausereignisses.
        mouse_x: Bildschirm-X-Position des Mausereignisses.
        height: Terminalhöhe (für Sichtbarkeits-Check).

    Returns:
        Index des getroffenen Eintrags, oder None.
    """
    i = mouse_y - MENU_START_ROW
    if i < 0 or i >= len(items):
        return None
    if MENU_START_ROW + i >= height - 3:
        return None
    _, label = items[i]
    item_width = MENU_ITEM_PREFIX_WIDTH + len(label)
    if not (ITEM_INDENT_X <= mouse_x < ITEM_INDENT_X + item_width):
        return None
    return i


def _compute_browse_column_layout(
    items: list[tuple[str, str]], width: int
) -> tuple[int, int, int]:
    """Berechnet Spaltenzahl, Spaltenbreite und Zeilenzahl für die Grid-Darstellung in curses_browse().

    Args:
        items: Liste von (value, label) Tuples.
        width: Terminalbreite.

    Returns:
        (num_columns, column_width, rows). column_width enthält Präfix
        (MENU_ITEM_PREFIX_WIDTH) und Spaltenabstand (MENU_COLUMN_GAP_X); rows ist
        die Zeilenzahl pro Spalte (aufgerundet). Bei sehr langen Labels ergibt
        sich num_columns == 1 (entspricht der bisherigen Einzelspalten-Darstellung).
    """
    max_label_width = max((len(label) for _, label in items), default=0)
    column_width = max_label_width + MENU_ITEM_PREFIX_WIDTH + MENU_COLUMN_GAP_X
    available_width = width - UI_PADDING_X
    num_columns = max(1, min(len(items), available_width // column_width))
    rows = -(-len(items) // num_columns)  # ceil ohne math-Import
    return num_columns, column_width, rows


def _render_browse_columns(
    stdscr: "curses.window",
    items: list[tuple[str, str]],
    current: int,
    scroll_offset: int,
    num_columns: int,
    column_width: int,
    rows: int,
    list_start_y: int,
    viewport_height: int,
    height: int,
) -> None:
    """Rendert die Dateiliste in curses_browse() spaltenweise (column-major, wie `ls`).

    Args:
        stdscr: Das Curses Hauptfenster.
        items: Liste von (value, label) Tuples.
        current: Aktuell gewählter Index (für Highlight).
        scroll_offset: Aktueller Scroll-Offset in Zeilen.
        num_columns: Anzahl Spalten (aus _compute_browse_column_layout()).
        column_width: Breite einer Spalte inkl. Präfix und Abstand.
        rows: Zeilenzahl pro Spalte.
        list_start_y: Bildschirm-Y-Position der ersten Listenzeile.
        viewport_height: Anzahl sichtbarer Listenzeilen.
        height: Terminalhöhe (für Sichtbarkeits-Check).
    """
    label_width = column_width - MENU_ITEM_PREFIX_WIDTH - MENU_COLUMN_GAP_X
    for col in range(num_columns):
        x = UI_PADDING_X + col * column_width
        col_start = col * rows
        col_end = min(col_start + rows, len(items))
        for row in range(viewport_height):
            idx = col_start + scroll_offset + row
            if idx >= col_end:
                break
            y = list_start_y + row
            if y >= height - 2:
                break
            _, label = items[idx]
            display = label[:label_width]
            if idx == current:
                stdscr.addstr(
                    y, x, f"> {display}", curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD
                )
            else:
                stdscr.addstr(y, x, f"  {display}")


def _browse_grid_item_at_position(
    items: list[tuple[str, str]],
    num_columns: int,
    column_width: int,
    rows: int,
    scroll_offset: int,
    list_start_y: int,
    viewport_height: int,
    mouse_y: int,
    mouse_x: int,
    height: int,
) -> int | None:
    """Ermittelt den Grid-Index unter dem Mauszeiger in curses_browse().

    Spiegelt die Geometrie von _render_browse_columns() (Spalten- und Zeilenzuordnung).

    Args:
        items: Liste von (value, label) Tuples.
        num_columns: Anzahl Spalten (aus _compute_browse_column_layout()).
        column_width: Breite einer Spalte inkl. Präfix und Abstand.
        rows: Zeilenzahl pro Spalte.
        scroll_offset: Aktueller Scroll-Offset in Zeilen.
        list_start_y: Bildschirm-Y-Position der ersten Listenzeile.
        viewport_height: Anzahl sichtbarer Listenzeilen.
        mouse_y: Bildschirm-Y-Position des Mausereignisses.
        mouse_x: Bildschirm-X-Position des Mausereignisses.
        height: Terminalhöhe (für Sichtbarkeits-Check).

    Returns:
        Index des getroffenen Eintrags, oder None.
    """
    row = mouse_y - list_start_y
    if row < 0 or row >= viewport_height or list_start_y + row >= height - 2:
        return None
    if mouse_x < UI_PADDING_X:
        return None
    col = (mouse_x - UI_PADDING_X) // column_width
    if col >= num_columns:
        return None
    col_start = col * rows
    idx = col_start + scroll_offset + row
    if idx >= min(col_start + rows, len(items)):
        return None
    return idx


def _confirm_choice_at_position(
    choices: list[str], choice_x: int, y: int, mouse_y: int, mouse_x: int
) -> int | None:
    """Ermittelt den Choice-Index unter dem Mauszeiger in curses_confirm().

    Horizontale Geometrie (zwei Choices in einer Zeile) statt vertikaler Liste –
    kein Scroll-Offset/Sichtbarkeits-Check nötig, die Zeile ist immer vollständig sichtbar.

    Args:
        choices: Choice-Labels (["Ja", "Nein"]).
        choice_x: X-Startposition der ersten Choice.
        y: Y-Position der Choice-Zeile.
        mouse_y: Bildschirm-Y-Position des Mausereignisses.
        mouse_x: Bildschirm-X-Position des Mausereignisses.

    Returns:
        Index der getroffenen Choice (0=Ja, 1=Nein), oder None.
    """
    if mouse_y != y:
        return None
    x = choice_x
    for i, choice in enumerate(choices):
        item_width = MENU_ITEM_PREFIX_WIDTH + len(choice)
        if x <= mouse_x < x + item_width:
            return i
        x += item_width + 2  # 2 = Trenner aus "  ".join() in curses_confirm()
    return None


def _load_login_shell_path() -> str | None:
    """Liest den PATH aus einer interaktiven Login-Shell des Users.

    Wird der Launcher außerhalb eines Login-Terminals gestartet, erbt er einen
    reduzierten PATH und Subprozesse finden Befehle wie `code` oder `claude`
    nicht. Interaktiv + Login, weil PATH-Setup sowohl in ~/.zprofile (Login)
    als auch in ~/.zshrc (nur interaktiv) liegen kann. Marker isolieren den
    PATH von stdout-Noise der rc-Dateien.

    Returns:
        Vollständiger PATH-String oder None wenn die Shell fehlschlägt.
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


def _fetch_claude_usage_stats() -> dict[str, Any] | None:
    """Liest Claude-Nutzungsdaten von der openusage-CLI (falls installiert).

    Returns:
        Dict mit Keys "session", "weekly", "generated_at" (Zeitpunkt der
        Abfrage, top-level "generatedAt") und "expires_at" (Ablauf des
        openusage-internen Caches, verschachtelt unter
        providers.<provider>.expiresAt), oder None wenn openusage fehlt,
        fehlschlägt oder unerwartete Daten liefert.
    """
    try:
        result = subprocess.run(
            [OPENUSAGE_BINARY, OPENUSAGE_PROVIDER],
            capture_output=True,
            text=True,
            timeout=OPENUSAGE_FETCH_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        provider = data["providers"][OPENUSAGE_PROVIDER]
        resources = provider["resources"]
        session = resources["session"]
        weekly = resources["weekly"]
        return {
            "session": {"used": session["used"], "resetsAt": session["resetsAt"]},
            "weekly": {"used": weekly["used"], "resetsAt": weekly["resetsAt"]},
            "generated_at": data["generatedAt"],
            "expires_at": provider["expiresAt"],
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


USAGE_CACHE_REQUIRED_KEYS = {
    "session_used",
    "session_resets_at",
    "weekly_used",
    "weekly_resets_at",
    "generated_at",
    "expires_at",
}


def _usage_stats_to_cache(usage: dict[str, Any]) -> dict[str, Any]:
    """Flacht ein _fetch_claude_usage_stats()-Ergebnis für die config.toml-Speicherung ab."""
    return {
        "session_used": usage["session"]["used"],
        "session_resets_at": usage["session"]["resetsAt"],
        "weekly_used": usage["weekly"]["used"],
        "weekly_resets_at": usage["weekly"]["resetsAt"],
        "generated_at": usage["generated_at"],
        "expires_at": usage["expires_at"],
    }


def _usage_stats_from_cache(cache: dict[str, Any]) -> dict[str, Any]:
    """Baut aus einem flachen usage_cache-Dict wieder die Form von _fetch_claude_usage_stats()."""
    return {
        "session": {"used": cache["session_used"], "resetsAt": cache["session_resets_at"]},
        "weekly": {"used": cache["weekly_used"], "resetsAt": cache["weekly_resets_at"]},
        "generated_at": cache["generated_at"],
        "expires_at": cache["expires_at"],
    }


def _format_relative_reset(reset_iso: str) -> str:
    """Formatiert einen ISO-Zeitstempel als relative Restzeit (z. B. "4d23h", "1h15m", "15m").

    Args:
        reset_iso: ISO-8601-Zeitstempel, ggf. mit "Z"-Suffix (UTC).

    Returns:
        Relative Restzeit bis zum Zeitstempel, "0m" falls bereits abgelaufen.
    """
    reset_dt = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
    total_minutes = max(int((reset_dt - datetime.now(timezone.utc)).total_seconds() // 60), 0)
    days, rem_minutes = divmod(total_minutes, MINUTES_PER_DAY)
    hours, minutes = divmod(rem_minutes, MINUTES_PER_HOUR)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def _format_absolute_time(timestamp_iso: str) -> str:
    """Formatiert einen ISO-Zeitstempel als lokale Uhrzeit (z. B. "14:32").

    Args:
        timestamp_iso: ISO-8601-Zeitstempel, ggf. mit "Z"-Suffix (UTC).

    Returns:
        Lokale Uhrzeit im Format "HH:MM".
    """
    timestamp_dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    return timestamp_dt.astimezone().strftime("%H:%M")


def _render_cheatsheet(stdscr: "curses.window", height: int, width: int) -> None:
    """Zeigt eine Vollbild-Übersicht aller Shortcuts (zweispaltig, Klammern ausgerichtet).

    Bleibt sichtbar bis der Aufrufer die nächste Taste abfängt (Press-and-dismiss).

    Args:
        stdscr: Das Curses Hauptfenster.
        height: Terminalhöhe.
        width: Terminalbreite.
    """
    stdscr.clear()
    stdscr.addstr(
        MENU_TITLE_ROW,
        UI_PADDING_X,
        "Shortcuts",
        curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
    )
    sep = "─" * (width - 4)
    stdscr.addstr(MENU_SEPARATOR_ROW, UI_PADDING_X, sep, curses.color_pair(COLOR_PAIR_ORANGE))

    lines = [f"[{key}] {label}" for key, label in SHORTCUT_LABELS.items()]
    split = -(-len(lines) // 2)  # ceil ohne math-Import
    col1, col2 = lines[:split], lines[split:]
    col1_width = max((len(line) for line in col1), default=0)
    col1_x = UI_PADDING_X
    col2_x = col1_x + col1_width + MENU_COLUMN_GAP_X

    for row, line in enumerate(col1):
        y = MENU_START_ROW + row
        if y >= height - 2:
            break
        stdscr.addstr(y, col1_x, line)
    if col2_x < width:
        for row, line in enumerate(col2):
            y = MENU_START_ROW + row
            if y >= height - 2:
                break
            stdscr.addstr(y, col2_x, line)

    if height > 3:
        stdscr.addstr(
            height - 2,
            UI_PADDING_X,
            "Beliebige Taste zum Schließen"[: width - 4],
            curses.color_pair(COLOR_PAIR_GRAY),
        )
    stdscr.refresh()


def curses_menu(
    stdscr: "curses.window",
    banner_text: str,
    status_text: str,
    menu_items: list[tuple[str, str]],
    default_index: int = 0,
    idle_timeout_ms: int | None = None,
    idle_refresh_predicate: Callable[[], bool] | None = None,
    usage_stats_text: str | None = None,
    mouse_enabled: bool = True,
) -> str | None:
    """Zeigt Hauptmenü mit Banner oben, Menü in zwei Spalten links und Status-Info rechts.

    Args:
        stdscr: Das Curses Hauptfenster.
        banner_text: Titel oben links.
        status_text: Mehrzeiliger Status; letzte Zeile = Footer, Rest = Info rechts.
        menu_items: Liste von (action_key, label) Tuples.
        default_index: Vorausgewählter Menü-Index.
        idle_timeout_ms: Poll-Intervall in ms für den Idle-Timer, oder None.
        idle_refresh_predicate: Liefert bei jedem Idle-Tick einen Vergleichswert;
            ändert sich der Wert gegenüber dem Stand bei Funktionseintritt,
            wird ein echter Refresh ausgelöst. None = jeder Tick refresht sofort.
        usage_stats_text: Mehrzeiliger Text für die Claude-Nutzungsstatistik-Spalte
            ganz rechts (openusage-CLI), oder None wenn keine Daten verfügbar sind.
        mouse_enabled: Ob Maus-Hover/Klick aktiviert werden soll (config.toml-Toggle).

    Returns:
        Action-Key des gewählten Eintrags, Sentinel-String oder None bei Abbruch.
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        # REPORT_MOUSE_POSITION zusätzlich zu BUTTON1_CLICKED, sonst meldet curses nur
        # Klicks, keine reine Bewegung (kein Hover-Highlight möglich).
        curses.mousemask(curses.BUTTON1_CLICKED | curses.REPORT_MOUSE_POSITION)
        sys.stdout.write(XTERM_ENABLE_MOUSE_MOTION_TRACKING)
        sys.stdout.flush()
    current = default_index

    if idle_timeout_ms is not None:
        stdscr.timeout(idle_timeout_ms)

    initial_predicate_state = (
        idle_refresh_predicate() if idle_refresh_predicate is not None else None
    )

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            # Status-Text aufteilen: letzte Zeile = Footer, Rest = Info-Zeilen
            status_lines = status_text.split("\n")
            footer = status_lines[-1].strip() if status_lines else ""
            info_lines = [line.strip() for line in status_lines[:-1]]

            # Menü in zwei Spalten aufteilen (inhaltliche Gruppierung, siehe WORKFLOW_ACTIONS)
            col1, col2 = _split_menu_columns(menu_items)
            col1_label_width = max((len(label) for _, label in col1), default=0)
            col2_label_width = max((len(label) for _, label in col2), default=0)

            col1_x = UI_PADDING_X
            col2_x = col1_x + col1_label_width + MENU_ITEM_PREFIX_WIDTH + MENU_COLUMN_GAP_X

            # Rechte Spalte dynamisch: an rechte Menüspalte anschließen + Puffer für Emoji + Abstand
            status_anchor_x = col2_x if col2 else col1_x
            status_anchor_width = col2_label_width if col2 else col1_label_width
            right_col = (
                status_anchor_x + status_anchor_width + MENU_ITEM_PREFIX_WIDTH + MENU_RIGHT_COL_BUFFER
            )

            # Claude-Nutzungsstatistik-Spalte ganz rechts, an Terminalbreite verankert
            usage_col_x = width - USAGE_STATS_COL_WIDTH
            show_usage_col = (
                usage_stats_text is not None
                and usage_col_x < width
                and usage_col_x - right_col >= USAGE_STATS_MIN_GAP
            )

            # Titel links, Versionsnummer rechts
            stdscr.addstr(
                MENU_TITLE_ROW,
                UI_PADDING_X,
                banner_text,
                curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
            )
            version_x = width - len(VERSION) - UI_PADDING_X
            if version_x > len(banner_text) + 4:
                stdscr.addstr(MENU_TITLE_ROW, version_x, VERSION)

            # Separator
            sep = "─" * (width - 4)
            stdscr.addstr(
                MENU_SEPARATOR_ROW, UI_PADDING_X, sep, curses.color_pair(COLOR_PAIR_ORANGE)
            )

            # Menü (zwei Spalten links)
            _render_menu_column(stdscr, col1, current, col1_x, height)
            if col2_x < width:
                _render_menu_column(stdscr, col2, current, col2_x, height)

            # Status-Info (rechts, neben den ersten Menü-Zeilen)
            status_right_boundary = (
                usage_col_x - MENU_COLUMN_GAP_X if show_usage_col else width - UI_PADDING_X
            )
            for i, line in enumerate(info_lines):
                y = MENU_START_ROW + i
                if y >= height - 2 or right_col >= width:
                    break
                max_len = status_right_boundary - right_col
                stdscr.addstr(
                    y, right_col, line[:max_len], curses.color_pair(COLOR_PAIR_GRAY)
                )

            # Claude-Nutzungsstatistik (rechts außen, openusage-CLI)
            if show_usage_col:
                for i, line in enumerate(usage_stats_text.split("\n")):
                    y = MENU_START_ROW + i
                    if y >= height - 2:
                        break
                    max_len = width - usage_col_x - UI_PADDING_X
                    stdscr.addstr(
                        y, usage_col_x, line.strip()[:max_len], curses.color_pair(COLOR_PAIR_GREEN)
                    )

            # Footer (unterste Zeile, kein Rahmen)
            if height > 3:
                max_footer = width - 4
                stdscr.addstr(
                    height - 2,
                    UI_PADDING_X,
                    footer[:max_footer],
                    curses.color_pair(COLOR_PAIR_GRAY),
                )

            stdscr.refresh()

            key = stdscr.getch()

            if key == -1:
                if (
                    idle_refresh_predicate is None
                    or idle_refresh_predicate() != initial_predicate_state
                ):
                    return "__idle_refresh__"
                continue
            elif _is_up_key(key):
                current = (current - 1) % len(menu_items)
            elif _is_down_key(key):
                current = (current + 1) % len(menu_items)
            elif _is_left_key(key) or _is_right_key(key):
                current = _swap_menu_column(current, col1, col2)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _menu_item_at_position(
                    col1, col2, col1_x, col2_x, col1_label_width, col2_label_width,
                    mouse_y, mouse_x, height,
                )
                if hit is None:
                    continue
                current = hit
                if bstate & curses.BUTTON1_CLICKED:
                    return menu_items[current][0]
            elif key == ord("\n") or key == KEY_SPACE:
                return menu_items[current][0]
            elif key == ord("q"):
                return None
            elif key == ord("r"):
                return "__refresh__"
            elif key == ord("x"):
                return "__toggle_ask_reset__"
            elif key == ord("o"):
                return "__toggle_overwrite_ask__"
            elif key == ord("h"):
                if idle_timeout_ms is not None:
                    stdscr.timeout(-1)
                _render_cheatsheet(stdscr, height, width)
                stdscr.getch()
                if idle_timeout_ms is not None:
                    stdscr.timeout(idle_timeout_ms)
                continue
            elif key == ord("s"):
                return "start"
            elif key == ord("t"):
                return "shell"
            elif key == ord("p"):
                return "plan"
            elif key == ord("e"):
                return "export_first"
            elif key == ord("i"):
                return "import_first"
            elif key == ord("v"):
                return "open_import_source"
    finally:
        # Mausmodus muss vor endwin() (in curses.wrapper) explizit deaktiviert werden,
        # sonst bleibt das Terminal in manchen Emulatoren im Mouse-Tracking-Modus
        # (Escape-Sequenz-Müll in Shell / nachfolgenden curses_*-Dialogen).
        if mouse_enabled:
            sys.stdout.write(XTERM_DISABLE_MOUSE_MOTION_TRACKING)
            sys.stdout.flush()
            curses.mousemask(0)


def curses_confirm(
    stdscr: "curses.window",
    message: str,
    default: bool = False,
    mouse_enabled: bool = True,
) -> bool:
    """Zeigt Ja/Nein Dialog.

    Args:
        stdscr: Das Curses Hauptfenster.
        message: Anzuzeigende Frage (kann Zeilenumbrüche enthalten).
        default: True wenn Ja vorausgewählt sein soll.
        mouse_enabled: Ob Maus-Hover/Klick aktiviert werden soll (config.toml-Toggle).

    Returns:
        True für Ja, False für Nein oder Abbruch.
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        curses.mousemask(curses.BUTTON1_CLICKED | curses.REPORT_MOUSE_POSITION)
        sys.stdout.write(XTERM_ENABLE_MOUSE_MOTION_TRACKING)
        sys.stdout.flush()
    current = 0 if default else 1
    choices = ["Ja", "Nein"]

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            # Message (mehrzeilig und zentriert)
            lines = message.split("\n")
            start_y = height // 2 - len(lines) - 2

            for i, line in enumerate(lines):
                x = max(0, (width - len(line)) // 2)
                stdscr.addstr(
                    start_y + i,
                    x,
                    line,
                    curses.color_pair(COLOR_PAIR_GRAY) | curses.A_BOLD,
                )

            # Choices
            y = start_y + len(lines) + 2
            choice_line = "  ".join(
                [f"> {c}" if i == current else f"  {c}" for i, c in enumerate(choices)]
            )
            stdscr.addstr(y, (width - len(choice_line)) // 2, choice_line)

            # Aktuelle Auswahl hervorheben
            choice_x = (width - len(choice_line)) // 2
            if current == 0:
                stdscr.addstr(
                    y,
                    choice_x,
                    f"> {choices[0]}",
                    curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(
                    y,
                    choice_x + len(f"> {choices[0]}") + 2,
                    f"> {choices[1]}",
                    curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD,
                )

            stdscr.refresh()

            key = stdscr.getch()

            if key == curses.KEY_LEFT:
                current = 0
            elif key == curses.KEY_RIGHT:
                current = 1
            elif key == KEY_TAB:
                current ^= 1  # Toggle zwischen Ja (0) und Nein (1)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _confirm_choice_at_position(choices, choice_x, y, mouse_y, mouse_x)
                if hit is None:
                    continue
                current = hit
                if bstate & curses.BUTTON1_CLICKED:
                    return current == 0
            elif key == ord("\n") or key == KEY_SPACE:
                return current == 0
            elif key == ord("y") or key == ord("j"):  # j=ja (Deutsch), y=yes (Englisch)
                return True
            elif key == ord("n"):
                return False
            elif key == KEY_ESC:
                return False
    finally:
        if mouse_enabled:
            sys.stdout.write(XTERM_DISABLE_MOUSE_MOTION_TRACKING)
            sys.stdout.flush()
            curses.mousemask(0)


def curses_input(
    stdscr: "curses.window",
    prompt: str,
    default: str = "",
) -> str | None:
    """Text-Eingabe Dialog mit Cursor-Support.

    Args:
        stdscr: Das Curses Hauptfenster.
        prompt: Anzuzeigender Eingabe-Hinweis.
        default: Vorausgefüllter Wert (editierbar).

    Returns:
        Eingegebener Text oder None bei Abbruch (ESC).
    """
    _init_curses_colors(stdscr)  # setzt curs_set(0), danach überschreiben
    curses.curs_set(1)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    y = height // 2
    stdscr.addstr(
        y - 2, UI_PADDING_X, prompt, curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD
    )
    stdscr.addstr(y, UI_PADDING_X, "> ")

    user_input = default
    cursor_pos = len(user_input)

    while True:
        stdscr.addstr(
            y, ITEM_INDENT_X, user_input + " " * (width - len(user_input) - 6)
        )
        stdscr.move(y, ITEM_INDENT_X + cursor_pos)
        stdscr.refresh()

        key = stdscr.getch()

        if key == ord("\n"):
            return user_input
        elif key == KEY_ESC:
            return None
        elif key == curses.KEY_BACKSPACE or key == KEY_BACKSPACE_DEL:
            if cursor_pos > 0:
                user_input = user_input[: cursor_pos - 1] + user_input[cursor_pos:]
                cursor_pos -= 1
        elif key == curses.KEY_LEFT:
            cursor_pos = max(0, cursor_pos - 1)
        elif key == curses.KEY_RIGHT:
            cursor_pos = min(len(user_input), cursor_pos + 1)
        elif KEY_SPACE <= key <= KEY_PRINTABLE_MAX:
            user_input = user_input[:cursor_pos] + chr(key) + user_input[cursor_pos:]
            cursor_pos += 1


@overload
def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int,
    allow_edit: Literal[True],
    mouse_enabled: bool = True,
) -> tuple[str | None, bool]: ...


@overload
def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int = ...,
    allow_edit: Literal[False] = ...,
    mouse_enabled: bool = True,
) -> str | None: ...


def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int = 0,
    allow_edit: bool = False,
    mouse_enabled: bool = True,
) -> tuple[str | None, bool] | str | None:
    """Auswahl-Dialog für Listen (z.B. History).

    Args:
        stdscr: Das Curses Hauptfenster.
        title: Überschrift des Dialogs.
        items: Liste von (value, label) Tuples.
        default_index: Vorausgewählter Index.
        allow_edit: Wenn True, gibt (value, edit_mode) zurück; Tab öffnet Editierdialog.
        mouse_enabled: Ob Maus-Hover/Klick aktiviert werden soll (config.toml-Toggle).

    Returns:
        Wenn allow_edit=False: Gewählter value-String oder None.
        Wenn allow_edit=True: Tuple (value, edit_mode) oder (None, False).
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        curses.mousemask(curses.BUTTON1_CLICKED | curses.REPORT_MOUSE_POSITION)
        sys.stdout.write(XTERM_ENABLE_MOUSE_MOTION_TRACKING)
        sys.stdout.flush()
    current = default_index

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            stdscr.addstr(
                2, UI_PADDING_X, title, curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD
            )

            # Items (Platz für Hint-Zeile am Ende lassen)
            for i, (_, label) in enumerate(items):
                y = MENU_START_ROW + i
                if y >= height - 3:
                    break
                if i == current:
                    stdscr.addstr(
                        y,
                        ITEM_INDENT_X,
                        f"> {label}",
                        curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD,
                    )
                else:
                    stdscr.addstr(y, ITEM_INDENT_X, f"  {label}")

            # Hint-Zeile
            if allow_edit:
                hint = "[Enter] Auswählen  [Tab] Bearbeiten  [ESC] Abbrechen"
            else:
                hint = "[Enter] Auswählen  [ESC] Abbrechen"
            stdscr.addstr(
                height - 2, UI_PADDING_X, hint, curses.color_pair(COLOR_PAIR_GRAY)
            )

            stdscr.refresh()

            key = stdscr.getch()

            if _is_up_key(key):
                current = (current - 1) % len(items)
            elif _is_down_key(key, include_tab=not allow_edit):
                current = (current + 1) % len(items)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _select_item_at_position(items, mouse_y, mouse_x, height)
                if hit is None:
                    continue
                current = hit
                if bstate & curses.BUTTON1_CLICKED:
                    if allow_edit:
                        return (items[current][0], False)
                    return items[current][0]
            elif allow_edit and key == KEY_TAB:  # Tab im Edit-Modus → Editierdialog öffnen
                return (items[current][0], True)
            elif key == ord("\n"):
                if allow_edit:
                    return (items[current][0], False)
                return items[current][0]
            elif key == KEY_ESC or key == ord("q"):
                if allow_edit:
                    return (None, False)
                return None
    finally:
        if mouse_enabled:
            sys.stdout.write(XTERM_DISABLE_MOUSE_MOTION_TRACKING)
            sys.stdout.flush()
            curses.mousemask(0)


def curses_browse(
    stdscr: "curses.window",
    title: str,
    summary: str,
    items: list[tuple[str, str]],
    mouse_enabled: bool = True,
) -> None:
    """Scrollbare Read-Only-Ansicht für Dateilisten, mehrspaltig (`ls`-artig) je nach Terminalbreite.

    Args:
        stdscr: Das Curses Hauptfenster.
        title: Überschrift der Ansicht.
        summary: Zusammenfassung (Dateianzahl, Gesamtgröße).
        items: Liste von (value, label) Tuples zum Anzeigen.
        mouse_enabled: Ob Maus-Hover/Klick aktiviert werden soll (config.toml-Toggle).
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        curses.mousemask(curses.BUTTON1_CLICKED | curses.REPORT_MOUSE_POSITION)
        sys.stdout.write(XTERM_ENABLE_MOUSE_MOTION_TRACKING)
        sys.stdout.flush()

    try:
        height, width = stdscr.getmaxyx()

        # Guard-Clause für zu kleine Terminals
        if height < 8 or width < 40:
            stdscr.addstr(0, 0, "Terminal zu klein!")
            stdscr.getch()
            return

        current = 0

        if not items:
            stdscr.addstr(
                2, UI_PADDING_X, title, curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD
            )
            stdscr.addstr(MENU_START_ROW, ITEM_INDENT_X, "Keine Dateien vorhanden.")
            stdscr.addstr(
                height - 2, UI_PADDING_X, "ESC Zurück", curses.color_pair(COLOR_PAIR_GRAY)
            )
            stdscr.refresh()
            while True:
                if stdscr.getch() == KEY_ESC:
                    return
            return

        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            # Verfügbare Zeilen: Header(3) + Summary(1) + Leerzeile(1) oben, Hint(2) unten
            viewport_height = height - 7

            stdscr.addstr(
                1, UI_PADDING_X, title, curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD
            )
            stdscr.addstr(2, UI_PADDING_X, summary, curses.color_pair(COLOR_PAIR_GRAY))

            # Spaltenlayout und Scroll-Offset berechnen (zeilenbasiert innerhalb der Spalte)
            num_columns, column_width, rows = _compute_browse_column_layout(items, width)
            current_row = current % rows
            scroll_offset = (
                max(0, current_row - viewport_height + 1) if current_row >= viewport_height else 0
            )

            # Dateiliste spaltenweise rendern
            list_start_y = 4
            _render_browse_columns(
                stdscr,
                items,
                current,
                scroll_offset,
                num_columns,
                column_width,
                rows,
                list_start_y,
                viewport_height,
                height,
            )

            # Position-Indikator und Hint
            pos_text = f"[{current + 1}/{len(items)}]"
            hint = "↑↓/j/k Navigieren  ←→/h/l Spalte wechseln | ESC Zurück"
            stdscr.addstr(
                height - 2, UI_PADDING_X, hint, curses.color_pair(COLOR_PAIR_GRAY)
            )
            stdscr.addstr(
                height - 2,
                width - len(pos_text) - UI_PADDING_X,
                pos_text,
                curses.color_pair(COLOR_PAIR_GRAY),
            )

            stdscr.refresh()

            key = stdscr.getch()

            if _is_up_key(key):
                current = (current - 1) % len(items)
            elif _is_down_key(key):
                current = (current + 1) % len(items)
            elif _is_left_key(key):
                current = max(0, current - rows)
            elif _is_right_key(key):
                current = min(len(items) - 1, current + rows)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _browse_grid_item_at_position(
                    items,
                    num_columns,
                    column_width,
                    rows,
                    scroll_offset,
                    list_start_y,
                    viewport_height,
                    mouse_y,
                    mouse_x,
                    height,
                )
                if hit is not None:
                    current = hit
            elif key == KEY_ESC:
                return
    finally:
        if mouse_enabled:
            sys.stdout.write(XTERM_DISABLE_MOUSE_MOTION_TRACKING)
            sys.stdout.flush()
            curses.mousemask(0)


def curses_message(
    stdscr: "curses.window",
    title: str,
    message: str,
) -> None:
    """Zeigt eine Meldung und wartet auf beliebigen Tastendruck.

    Args:
        stdscr: Das Curses Hauptfenster.
        title: Überschrift der Meldung.
        message: Meldungstext (kann Zeilenumbrüche enthalten).
    """
    _init_curses_colors(stdscr)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    y = height // 2 - 3
    stdscr.addstr(
        y,
        max(0, (width - len(title)) // 2),
        title,
        curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
    )

    lines = message.split("\n")
    for i, line in enumerate(lines):
        stdscr.addstr(
            y + 2 + i,
            max(0, (width - len(line)) // 2),
            line,
            curses.color_pair(COLOR_PAIR_GRAY),
        )

    hint = "[ Beliebige Taste drücken ]"
    stdscr.addstr(y + 2 + len(lines) + 1, max(0, (width - len(hint)) // 2), hint)
    stdscr.refresh()
    stdscr.getch()


def _toml_scalar(value: Any) -> str:
    """Wandelt einen skalaren Config-Wert oder eine Liste von Strings in TOML-Literal-Syntax um.

    Args:
        value: str (inkl. leer), bool, int, float oder list[str].

    Returns:
        TOML-Literal-Darstellung des Werts.

    Raises:
        TypeError: Bei einem im Config-Schema nicht vorkommenden Typ.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Nicht unterstützter Config-Typ für TOML: {type(value)}")


def _toml_table_block(name: str, table: dict[str, str]) -> str:
    """Baut einen [name]-Tabellenblock aus einem Dict[str, str] (z. B. claude_env).

    Args:
        name: Tabellenname.
        table: Flaches Dict mit String-Werten.

    Returns:
        TOML-Tabellenblock inkl. Header.
    """
    lines = [f"[{name}]"]
    lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in table.items())
    return "\n".join(lines)


def _toml_array_of_tables_block(name: str, entries: list[dict[str, Any]]) -> str:
    """Baut wiederholte [[name]]-Blöcke aus einer Liste flacher Dicts (z. B. history).

    Args:
        name: Tabellenname.
        entries: Liste flacher Dicts; jeder Eintrag wird ein eigener Block.

    Returns:
        Aneinandergereihte TOML-Array-of-Tables-Blöcke.
    """
    blocks = []
    for entry in entries:
        lines = [f"[[{name}]]"]
        lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in entry.items())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _dump_toml(data: dict[str, Any]) -> str:
    """Serialisiert das Config-Dict als lesbares TOML.

    Deckt genau die im Config-Schema vorkommenden Typen ab: Skalare und Listen von
    Strings werden als flache key = value Zeilen geschrieben (müssen vor jedem
    Tabellenblock stehen), ein Dict[str, str] als [key]-Tabelle, eine nicht-leere
    Liste von Dicts als [[key]] Array-of-Tables. Kein generischer TOML-Writer.

    Args:
        data: Config-Dictionary.

    Returns:
        Vollständiger TOML-Text inkl. abschließendem Zeilenumbruch.
    """
    scalar_lines = []
    table_blocks = []
    for key, value in data.items():
        if isinstance(value, dict):
            table_blocks.append(_toml_table_block(key, value))
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            table_blocks.append(_toml_array_of_tables_block(key, value))
        else:
            scalar_lines.append(f"{key} = {_toml_scalar(value)}")

    sections = ["\n".join(scalar_lines), *table_blocks]
    return "\n\n".join(section for section in sections if section) + "\n"


class ConfigManager:
    """Verwaltet config.toml mit Export/Import-History."""

    def __init__(self, config_path: Path | None = None):
        """Initialisiert den ConfigManager.

        Args:
            config_path: Pfad zur Config-Datei. Standardmäßig config.toml im Script-Verzeichnis.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.toml"
        self.config_path = Path(config_path)
        self.config = self.load_config()

    def load_config(self) -> dict[str, Any]:
        """Lädt Config oder erstellt Default falls nicht vorhanden.

        Returns:
            Config-Dictionary mit allen Einstellungen.

        Raises:
            tomllib.TOMLDecodeError: Bei korrupter TOML-Datei (wird abgefangen, Backup erstellt).
        """
        default_config = {
            "history": [],
            "max_history_entries": 10,
            "export_ignore_patterns": [],
            "import_ignore_patterns": [],
            "claude_env": {},
            "claude_instruction": "",
            "ask_for_reset": True,
            "dont_ask_on_export_overwrite": False,
            "plan_idle_timer_enabled": True,
            "plan_idle_timer_duration": DEFAULT_PLAN_IDLE_TIMER_DURATION,
            "mouse_navigation_enabled": True,
            "recent_shortcuts": [],
            "usage_cache": {},
        }

        if not self.config_path.exists():
            self.save_config(default_config)
            return default_config

        try:
            with open(self.config_path, "rb") as f:
                config = tomllib.load(f) or {}
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        except tomllib.TOMLDecodeError as e:
            # Bei korrupter Config: Backup erstellen und Default verwenden
            print(f"Config-Datei korrupt: {e}")
            backup_path = self.config_path.with_suffix(".toml.bak")
            if self.config_path.exists():
                shutil.copy(self.config_path, backup_path)
            return default_config

    def reload(self) -> None:
        """Lädt Config neu von Platte, um Änderungen anderer Instanzen zu übernehmen."""
        self.config = self.load_config()

    def save_config(self, config: dict[str, Any] | None = None) -> None:
        """Speichert Config in TOML.

        Args:
            config: Zu speicherndes Dictionary. Wenn None, wird self.config verwendet.
        """
        if config is None:
            config = self.config

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            f.write(_dump_toml(config))

    def add_to_history(self, path: Path, history_type: str) -> None:
        """Fügt Pfad zur History hinzu, limitiert auf max_history_entries.

        Args:
            path: Pfad der Export- oder Import-Operation.
            history_type: "export" oder "import".

        Raises:
            ValueError: Wenn history_type ungültig ist.
        """
        if history_type not in ["export", "import"]:
            raise ValueError(f"Invalid history_type: {history_type}")

        self.reload()
        history = self.config["history"]
        path_str = str(path.absolute())

        # Duplikate pro (Pfad, Typ) entfernen, dann neuen Eintrag vorne einfügen;
        # Alt-Einträge ohne type-Feld gelten als Treffer und werden ersetzt
        history = [
            h
            for h in history
            if h.get("path") != path_str or h.get("type", history_type) != history_type
        ]
        history.insert(
            0,
            {
                "path": path_str,
                "timestamp": datetime.now().isoformat(),
                "type": history_type,
            },
        )

        self.config["history"] = history[: self.config["max_history_entries"]]
        self.save_config()

    def get_history(self, history_type: str) -> list[dict]:
        """Gibt History-Liste zurück.

        Args:
            history_type: "export" oder "import".

        Returns:
            Liste der History-Einträge dieses Typs (Alt-Einträge ohne type-Feld
            zählen für beide Typen).

        Raises:
            ValueError: Wenn history_type ungültig ist.
        """
        if history_type not in ["export", "import"]:
            raise ValueError(f"Invalid history_type: {history_type}")
        return [
            h
            for h in self.config.get("history", [])
            if h.get("type", history_type) == history_type
        ]

    def record_reset(self) -> None:
        """Speichert aktuellen Zeitstempel als letzten Reset-Zeitpunkt."""
        self.reload()
        self.config["last_reset_timestamp"] = datetime.now().isoformat()
        self.save_config()

    def toggle_bool_option(self, key: str) -> bool:
        """Negiert Bool-Wert in Config und speichert zurück.

        Args:
            key: Config-Schlüssel des Bool-Werts.

        Returns:
            Neuer Wert nach dem Toggle.
        """
        self.reload()
        self.config[key] = not self.config.get(key, False)
        self.save_config()
        return self.config[key]

    def record_shortcut_usage(self, shortcut: str) -> None:
        """Merkt sich shortcut als zuletzt verwendet (neuestes zuerst, dedupliziert).

        Args:
            shortcut: Ein-Buchstaben-Hotkey der ausgeführten Aktion.
        """
        self.reload()
        recent = [s for s in self.config.get("recent_shortcuts", []) if s != shortcut]
        recent.insert(0, shortcut)
        self.config["recent_shortcuts"] = recent[:RECENT_SHORTCUTS_MAX_ENTRIES]
        self.save_config()


class WorkspaceManager:
    """Verwaltet Workspace-Operationen (Reset, Export, Import)."""

    def __init__(
        self,
        workspace_path: Path,
        config_manager: "ConfigManager | None" = None,
    ):
        """Initialisiert den WorkspaceManager.

        Args:
            workspace_path: Pfad zum Workspace-Verzeichnis.
            config_manager: Optionaler ConfigManager für Ignore-Patterns und Config-Zugriff.
        """
        self.workspace = Path(workspace_path)
        self.settings_file = self.workspace / "settings.local.json"
        self.config_manager = config_manager

    def is_empty(self) -> bool:
        """Prüft ob Workspace leer ist (ignoriert settings.local.json).

        Returns:
            True wenn keine relevanten Dateien vorhanden sind.
        """
        if not self.workspace.exists():
            return True
        return not any(
            item.is_file() and item != self.settings_file
            for item in self.workspace.rglob("*")
        )

    def get_status(self) -> dict:
        """Gibt Status zurück: Leer-Flag, Dateianzahl und Größe in MB.

        Returns:
            Dict mit Schlüsseln: is_empty, file_count, size_mb.
        """
        if self.is_empty():
            return {"is_empty": True, "file_count": 0, "size_mb": 0.0}

        relevant_files = [
            item
            for item in self.workspace.rglob("*")
            if item.is_file() and item != self.settings_file
        ]
        file_count = len(relevant_files)
        total_size = sum(item.stat().st_size for item in relevant_files)

        return {
            "is_empty": False,
            "file_count": file_count,
            "size_mb": round(total_size / BYTES_PER_MB, 2),
        }

    def _build_content_entry(self, path: Path) -> tuple[str, str, float]:
        """Baut (relativer_pfad, Anzeigetext, mtime) für einen Datei- oder Punkt-Ordner-Eintrag.

        Bei Verzeichnissen (Punkt-Ordner) wird die Größe rekursiv aus allen
        enthaltenen Dateien summiert, statt den Ordnerinhalt einzeln aufzulisten.
        """
        rel_path = str(path.relative_to(self.workspace))
        if path.is_dir():
            size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        else:
            size = path.stat().st_size

        if size < BYTES_PER_KB:
            size_str = f"{size} B"
        elif size < BYTES_PER_MB:
            size_str = f"{size / BYTES_PER_KB:.1f} KB"
        else:
            size_str = f"{size / BYTES_PER_MB:.1f} MB"

        icon = "📁" if path.is_dir() else "📄"
        label = f"{icon} {rel_path}  ({size_str})"

        return rel_path, label, path.stat().st_mtime

    def get_contents(self) -> list[tuple[str, str]]:
        """Gibt Dateiliste zurück: [(relative_path, display_label), ...].

        Punkt-Ordner (z. B. .git) werden als einzelner Eintrag mit rekursiv
        berechneter Gesamtgröße geführt, ihr Inhalt wird nicht aufgelistet.
        Punkt-Dateien (z. B. .env) erscheinen normal in der Liste.
        Ordner-Einträge tragen ein 📁-Präfix, Datei-Einträge ein 📄-Präfix.

        Returns:
            Nach letzter Änderung sortierte Liste (neueste zuerst) von
            (relativer_pfad, Anzeigetext) Tuples.
        """
        if not self.workspace.exists():
            return []

        entries = []
        for root, dirnames, filenames in os.walk(self.workspace):
            root_path = Path(root)
            kept_dirnames = []
            for dirname in dirnames:
                if dirname.startswith("."):
                    entries.append(self._build_content_entry(root_path / dirname))
                else:
                    kept_dirnames.append(dirname)
            dirnames[:] = kept_dirnames

            for filename in filenames:
                entries.append(self._build_content_entry(root_path / filename))

        # Neueste zuerst, damit zuletzt bearbeitete Einträge in curses_browse() oben stehen.
        entries.sort(key=lambda entry: entry[2], reverse=True)
        return [(rel_path, label) for rel_path, label, _ in entries]

    @staticmethod
    def _delete_item(item: Path) -> None:
        """Löscht eine Datei oder ein Verzeichnis rekursiv.

        Args:
            item: Zu löschender Dateisystem-Eintrag.
        """
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)

    def _clear_directory(self) -> None:
        """Löscht alle Einträge in Workspace oder erstellt es neu."""
        if self.workspace.exists():
            for item in self.workspace.iterdir():
                self._delete_item(item)
        else:
            self.workspace.mkdir(parents=True, exist_ok=True)

    def _get_exclude_args(self, pattern_key: str) -> list[str]:
        """Baut rsync --exclude-Argumente aus den konfigurierten Ignore-Patterns.

        Args:
            pattern_key: Config-Schlüssel für die Patterns.

        Returns:
            Liste von "--exclude=<pattern>"-Argumenten (leer wenn keine Patterns).
        """
        patterns = (
            self.config_manager.config.get(pattern_key, [])
            if self.config_manager
            else []
        )
        return [f"--exclude={pattern}" for pattern in patterns]

    def _rsync_mirror(
        self,
        source: Path,
        destination: Path,
        pattern_key: str,
        delete_excluded: bool,
    ) -> None:
        """Spiegelt source nach destination via rsync (überträgt auch Löschungen).

        Args:
            source: Quell-Verzeichnis (Inhalt wird kopiert).
            destination: Ziel-Verzeichnis (wird bei Bedarf erstellt).
            pattern_key: Config-Schlüssel für die Ignore-Patterns.
            delete_excluded: True löscht auch excluded Einträge im Ziel,
                False lässt sie unangetastet.

        Raises:
            OSError: Wenn rsync fehlt oder mit Fehler endet.
        """
        cmd = [RSYNC_BINARY, *RSYNC_BASE_ARGS]
        if delete_excluded:
            cmd.append(RSYNC_DELETE_EXCLUDED_ARG)
        cmd.extend(self._get_exclude_args(pattern_key))
        cmd.extend([f"{source}/", str(destination)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise OSError("rsync wurde nicht gefunden (Installation prüfen)") from e
        if result.returncode != 0:
            stderr = result.stderr.strip() or "unbekannter Fehler"
            raise OSError(f"rsync fehlgeschlagen (Exit {result.returncode}): {stderr}")

    @staticmethod
    def _is_file_ignored(filename: str, patterns: list[str]) -> str | None:
        """Gibt das erste passende Ignore-Pattern zurück oder None.

        Args:
            filename: Zu prüfender Dateiname.
            patterns: Liste von fnmatch-Patterns.

        Returns:
            Das erste passende Pattern oder None wenn kein Pattern zutrifft.
        """
        return next(
            (pattern for pattern in patterns if fnmatch.fnmatch(filename, pattern)),
            None,
        )

    def _is_mouse_navigation_enabled(self) -> bool:
        """Liest mouse_navigation_enabled aus der Config (Default True, auch ohne ConfigManager).

        Returns:
            True wenn Maus-Hover/Klick in curses_confirm() aktiviert werden soll.
        """
        return (
            self.config_manager.config.get("mouse_navigation_enabled", True)
            if self.config_manager
            else True
        )

    def _confirm_overwrite(self, destination: Path) -> bool:
        """Fragt Bestätigung zum Überschreiben, sofern Config es nicht deaktiviert.

        Args:
            destination: Zu überschreibendes Ziel.

        Returns:
            True wenn überschrieben werden soll, False bei Abbruch.
        """
        dont_ask = (
            self.config_manager.config.get("dont_ask_on_export_overwrite", False)
            if self.config_manager
            else False
        )
        if dont_ask:
            return True
        return curses.wrapper(
            curses_confirm,
            f"Das Ziel ({destination}) existiert bereits.\nZiel wird synchronisiert – überzählige Dateien im Ziel werden gelöscht!\nFortfahren?",
            default=False,
            mouse_enabled=self._is_mouse_navigation_enabled(),
        )

    def reset(self) -> bool:
        """Löscht Workspace vollständig (alle Dateien und Verzeichnisse).

        Returns:
            True bei Erfolg, False bei Fehler.
        """
        try:
            self._clear_directory()
            print("✓ Workspace erfolgreich zurückgesetzt")
            return True
        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except OSError as e:
            print(f"✗ Fehler beim Reset: {e}")
            return False

    def export_to(self, destination: Path) -> bool:
        """Exportiert Workspace zu Ziel-Pfad (Folder Mode).

        Args:
            destination: Ziel-Verzeichnis für den Export.

        Returns:
            True bei Erfolg, False bei Fehler oder Abbruch.
        """
        try:
            destination = Path(destination)

            if not destination.parent.exists():
                curses.wrapper(
                    curses_message,
                    "Fehler",
                    f"Elternverzeichnis existiert nicht:\n{destination.parent}",
                )
                return False

            if destination.exists() and not self._confirm_overwrite(destination):
                return False

            self._rsync_mirror(
                self.workspace,
                destination,
                "export_ignore_patterns",
                delete_excluded=False,
            )

            print(f"✓ Erfolgreich exportiert nach: {destination}")

            ask_for_reset = (
                self.config_manager.config.get("ask_for_reset", True)
                if self.config_manager
                else True
            )
            if ask_for_reset:
                if curses.wrapper(
                    curses_confirm,
                    "Workspace jetzt zurücksetzen?",
                    default=False,
                    mouse_enabled=self._is_mouse_navigation_enabled(),
                ):
                    return self.reset()

            return True

        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except OSError as e:
            print(f"✗ Fehler beim Export: {e}")
            return False

    def export_file_to(self, rel_file_path: str, destination: Path) -> bool:
        """Exportiert eine einzelne Datei aus Workspace nach destination.

        Args:
            rel_file_path: Relativer Pfad der Quelldatei innerhalb von Workspace.
            destination: Zieldatei-Pfad.

        Returns:
            True bei Erfolg, False bei Fehler.
        """
        source_file = self.workspace / rel_file_path

        if not source_file.exists():
            curses.wrapper(
                curses_message, "Fehler", f"Datei nicht gefunden:\n{source_file}"
            )
            return False

        # Warnung wenn Datei einem Ignore-Pattern entspricht (kein Abbruch)
        ignore_patterns = (
            self.config_manager.config.get("export_ignore_patterns", [])
            if self.config_manager
            else []
        )
        matched_pattern = self._is_file_ignored(source_file.name, ignore_patterns)
        if matched_pattern:
            curses.wrapper(
                curses_message,
                "Warnung",
                f"Datei entspricht Ignore-Pattern '{matched_pattern}'.\nExport wird trotzdem durchgeführt.",
            )

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
            return True
        except PermissionError as e:
            curses.wrapper(curses_message, "Fehler", f"Keine Berechtigung:\n{e}")
            return False
        except OSError as e:
            curses.wrapper(curses_message, "Fehler", f"Fehler beim Export:\n{e}")
            return False

    def import_file_from(self, source_file: Path) -> bool:
        """Importiert eine einzelne Datei nach Workspace-Root.

        Args:
            source_file: Quelldatei-Pfad.

        Returns:
            True bei Erfolg, False bei Fehler.
        """
        if not source_file.exists():
            curses.wrapper(
                curses_message, "Fehler", f"Quelldatei nicht gefunden:\n{source_file}"
            )
            return False

        # Warnung wenn Datei einem Ignore-Pattern entspricht (kein Abbruch)
        ignore_patterns = (
            self.config_manager.config.get("import_ignore_patterns", [])
            if self.config_manager
            else []
        )
        matched_pattern = self._is_file_ignored(source_file.name, ignore_patterns)
        if matched_pattern:
            curses.wrapper(
                curses_message,
                "Warnung",
                f"Datei entspricht Ignore-Pattern '{matched_pattern}'.\nImport wird trotzdem durchgeführt.",
            )

        try:
            destination = self.workspace / source_file.name
            shutil.copy2(source_file, destination)
            return True
        except PermissionError as e:
            curses.wrapper(curses_message, "Fehler", f"Keine Berechtigung:\n{e}")
            return False
        except OSError as e:
            curses.wrapper(curses_message, "Fehler", f"Fehler beim Import:\n{e}")
            return False

    def import_from(self, source: Path) -> bool:
        """Importiert Workspace von Quell-Pfad (Folder Mode).

        Args:
            source: Quell-Verzeichnis für den Import.

        Returns:
            True bei Erfolg, False bei Fehler oder Abbruch.
        """
        try:
            source = Path(source)

            if not source.exists():
                curses.wrapper(
                    curses_message, "Fehler", f"Quelle nicht gefunden:\n{source}"
                )
                return False

            if not source.is_dir():
                curses.wrapper(
                    curses_message, "Fehler", f"Quelle ist kein Verzeichnis:\n{source}"
                )
                return False

            if not self.is_empty():
                confirm = curses.wrapper(
                    curses_confirm,
                    "Alle Daten im Workspace werden beim Import gelöscht!\nFortfahren?",
                    default=False,
                    mouse_enabled=self._is_mouse_navigation_enabled(),
                )
                if not confirm:
                    return False

            self._rsync_mirror(
                source, self.workspace, "import_ignore_patterns", delete_excluded=True
            )

            print(f"✓ Erfolgreich importiert von: {source}")
            return True

        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except OSError as e:
            print(f"✗ Fehler beim Import: {e}")
            return False


class LauncherApp:
    """Haupt-Controller für den Launcher."""

    def __init__(
        self,
        workspace: Path,
        config_manager: ConfigManager,
        claude_binary: Path,
        export_path: Path | None = None,
        import_path: Path | None = None,
    ):
        """Initialisiert die LauncherApp.

        Args:
            workspace: Pfad zum Workspace-Verzeichnis.
            config_manager: ConfigManager-Instanz.
            claude_binary: Pfad zum Claude Binary.
            export_path: Optionaler Direkt-Export-Pfad (CLI-Argument).
            import_path: Optionaler Direkt-Import-Pfad (CLI-Argument).
        """
        self.config_manager = config_manager
        self.workspace_manager = WorkspaceManager(workspace, config_manager)
        self.claude_binary = Path(claude_binary)
        self.export_path = export_path
        self.import_path = import_path

    def _plan_swap_file_exists(self) -> bool:
        """Prüft ob Plan.md gerade in vim geöffnet ist (Swap-Datei .Plan.md.swp vorhanden)."""
        swap_file = self.workspace_manager.workspace / ".Plan.md.swp"
        return swap_file.exists()

    def _get_default_menu_index(self, menu_items: list[tuple[str, str]]) -> int:
        """Setzt den Cursor auf 'Sitzung starten' wenn Plan.md gerade in vim bearbeitet wird."""
        if not self._plan_swap_file_exists():
            return 0
        for index, (action, _label) in enumerate(menu_items):
            if action == "start":
                return index
        return 0

    def _get_plan_idle_timer_interval_ms(self) -> int | None:
        """Berechnet das Poll-Intervall in ms für den Plan-Idle-Timer, oder None wenn deaktiviert."""
        if not self.config_manager.config.get("plan_idle_timer_enabled", True):
            return None
        duration_seconds = self.config_manager.config.get(
            "plan_idle_timer_duration", DEFAULT_PLAN_IDLE_TIMER_DURATION
        )
        if not isinstance(duration_seconds, (int, float)) or duration_seconds <= 0:
            return None
        return int(duration_seconds * MILLISECONDS_PER_SECOND)

    def _get_cached_usage_stats(self) -> dict[str, Any] | None:
        """Liefert Claude-Nutzungsdaten aus config.toml, ruft openusage nur bei Bedarf neu ab.

        Ein Cache-Eintrag gilt bis "expires_at" als gültig und wird dann ohne
        Subprocess-Aufruf zurückgegeben. Schlägt ein nötiger Neu-Abruf fehl (openusage
        fehlt/Timeout/Fehler), wird als Fallback der letzte bekannte Cache-Wert
        zurückgegeben statt die Anzeige auszublenden.

        Returns:
            Dict in der Form von _fetch_claude_usage_stats(), oder None wenn weder
            Cache noch Live-Abfrage Daten liefern.
        """
        self.config_manager.reload()
        cache = self.config_manager.config.get("usage_cache", {})
        has_cache = USAGE_CACHE_REQUIRED_KEYS.issubset(cache)

        if has_cache:
            expires_at = datetime.fromisoformat(cache["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < expires_at:
                return _usage_stats_from_cache(cache)

        fresh = _fetch_claude_usage_stats()
        if fresh is not None:
            self.config_manager.config["usage_cache"] = _usage_stats_to_cache(fresh)
            self.config_manager.save_config()
            return fresh

        return _usage_stats_from_cache(cache) if has_cache else None

    def _is_mouse_navigation_enabled(self) -> bool:
        """Ob Maus-Hover/Klick in curses_menu/curses_select/curses_browse aktiv ist."""
        return self.config_manager.config.get("mouse_navigation_enabled", True)

    def get_menu_items(self) -> list[tuple[str, str]]:
        """Generiert Menü-Items basierend auf Workspace-Status.

        Returns:
            Liste von (action_key, label) Tuples für das Hauptmenü.
        """
        is_empty = self.workspace_manager.is_empty()
        items: list[tuple[str, str]] = []

        items.append(("plan", "📝 Plan schreiben"))
        items.append(("start", "▶️  Sitzung starten"))

        if not is_empty:
            items.append(("export", "⤴️  Exportieren"))

        items.append(("import", "⤵️  Importieren"))
        items.append(("open_import_source", "🧭 Importquelle in VS Code öffnen"))

        if not is_empty:
            items.append(("browse", "📂 Inhalt von Workspace anzeigen"))

        items.append(("shell", "🖥️  Shell öffnen"))

        if not is_empty:
            items.append(("reset", "🔄 Reset"))

        return items

    def _build_status_text(self, status: dict) -> str:
        """Generiert den mehrzeiligen Status-String für das Hauptmenü.

        Args:
            status: Status-Dict von WorkspaceManager.get_status().

        Returns:
            Mehrzeiliger String: Info-Zeilen + Footer als letzte Zeile.
        """
        workspace_path = str(self.workspace_manager.workspace)

        recent_shortcuts = self.config_manager.config.get("recent_shortcuts", [])
        footer_segments = ["[h] Hilfe"]
        footer_segments += [
            f"[{key}] {SHORTCUT_LABELS[key]}" for key in recent_shortcuts if key in SHORTCUT_LABELS
        ]
        footer_segments.append("[q] Beenden")
        footer = "  " + "  ".join(footer_segments)

        all_history = self.config_manager.config.get("history", [])
        last_export = next((h for h in all_history if h.get("type") == "export"), None)
        last_import = next((h for h in all_history if h.get("type") == "import"), None)
        last_reset_ts = self.config_manager.config.get("last_reset_timestamp")
        export_line = self._get_export_line(last_export, last_reset_ts)
        import_line = self._get_import_line(last_import)

        content_line = (
            "   (leer)"
            if status["is_empty"]
            else f"   {status['file_count']} Dateien · {status['size_mb']} MB"
        )

        return f"📁 {workspace_path}\n{content_line}\n{export_line}{import_line}{footer}"

    @staticmethod
    def _get_export_line(last_export: dict | None, last_reset_ts: str | None) -> str:
        """Gibt Export-Info-Zeile zurück, wenn Export neuer als letzter Reset.

        Args:
            last_export: Letzter Export-Eintrag aus der History oder None.
            last_reset_ts: ISO-Timestamp des letzten Resets oder None.

        Returns:
            Formatierte Export-Zeile mit Newline oder leerer String.
        """
        if not last_export:
            return ""
        export_ts = datetime.fromisoformat(last_export["timestamp"])
        reset_ts = datetime.fromisoformat(last_reset_ts) if last_reset_ts else None
        if reset_ts is None or export_ts > reset_ts:
            folder_name = Path(last_export["path"]).name
            return f"   Letzter Export: {export_ts.strftime('%d.%m.%Y %H:%M')} ({folder_name})\n"
        return ""

    @staticmethod
    def _get_import_line(last_import: dict | None) -> str:
        """Gibt Import-Info-Zeile zurück, wenn ein Import in der History existiert.

        Args:
            last_import: Letzter Import-Eintrag aus der History oder None.

        Returns:
            Formatierte Import-Zeile mit Newline oder leerer String.
        """
        if not last_import:
            return ""
        import_ts = datetime.fromisoformat(last_import["timestamp"])
        folder_name = Path(last_import["path"]).name
        return f"   Letzter Import: {import_ts.strftime('%d.%m.%Y %H:%M')} ({folder_name})\n"

    @staticmethod
    def _build_usage_stats_text(usage: dict[str, Any] | None) -> str | None:
        """Baut den Text für die Claude-Nutzungsstatistik-Spalte (openusage-CLI).

        Args:
            usage: Ergebnis von LauncherApp._get_cached_usage_stats() oder None.

        Returns:
            Vierzeiliger Status-String oder None wenn keine Daten verfügbar sind.
        """
        if usage is None:
            return None
        session = usage["session"]
        weekly = usage["weekly"]
        session_reset = _format_relative_reset(session["resetsAt"])
        weekly_reset = _format_relative_reset(weekly["resetsAt"])
        updated_at = _format_absolute_time(usage["generated_at"])
        return (
            f"⚡ Claude Nutzung\n"
            f"Session {session['used']}% · {session_reset}\n"
            f"Weekly  {weekly['used']}% · {weekly_reset}\n"
            f"Aktualisiert {updated_at}"
        )

    def _handle_sentinel(self, result: str) -> bool:
        """Verarbeitet Sentinel-Rückgaben aus dem Menü (Refresh, Toggle-Hotkeys).

        `"__refresh__"` (manueller Tastendruck `r`) trackt den Shortcut zusätzlich,
        `"__idle_refresh__"` (automatischer Plan-Idle-Timer) bewusst nicht.

        Args:
            result: Rückgabewert von curses_menu.

        Returns:
            True wenn ein Sentinel verarbeitet wurde (Loop soll fortgesetzt werden).
        """
        if result == "__refresh__":
            self.config_manager.reload()
            self.config_manager.record_shortcut_usage("r")
            return True
        if result == "__idle_refresh__":
            self.config_manager.reload()
            return True
        if result == "__toggle_ask_reset__":
            self.config_manager.toggle_bool_option("ask_for_reset")
            return True
        if result == "__toggle_overwrite_ask__":
            self.config_manager.toggle_bool_option("dont_ask_on_export_overwrite")
            return True
        return False

    def select_path_with_history(self, history_type: str) -> Path | None:
        """Pfad-Auswahl mit History oder manuelle Eingabe.

        Enter = Pfad direkt übernehmen, Tab = Editierdialog öffnen.

        Args:
            history_type: "export" oder "import" für kontextspezifische Labels.

        Returns:
            Gewählter Pfad oder None bei Abbruch.
        """
        if history_type == "export":
            select_title = "Export-Ziel auswählen:"
            input_prompt = "Ziel-Pfad eingeben:"
            input_edit_prompt = "Ziel-Pfad anpassen:"
        else:
            select_title = "Import-Quelle auswählen:"
            input_prompt = "Quell-Pfad eingeben:"
            input_edit_prompt = "Quell-Pfad anpassen:"

        history = self.config_manager.get_history(history_type)

        if history:
            history_items = self._build_history_items(history)
            history_items.append(("__custom__", "📝 Neuen Pfad eingeben"))

            raw = curses.wrapper(
                curses_select,
                select_title,
                history_items,
                0,
                True,
                self._is_mouse_navigation_enabled(),
            )
            selected, edit_mode = raw if raw is not None else (None, False)

            if selected is None:
                return None

            if selected == "__custom__":
                path_input = curses.wrapper(curses_input, input_prompt, "")
            elif edit_mode:
                path_input = curses.wrapper(curses_input, input_edit_prompt, selected)
            else:
                path_input = selected
        else:
            path_input = curses.wrapper(curses_input, input_prompt, "")

        if not path_input or not path_input.strip():
            return None

        return Path(path_input).expanduser()

    @staticmethod
    def _build_history_items(history: list[dict]) -> list[tuple[str, str]]:
        """Bereitet History-Einträge für curses_select vor.

        Args:
            history: Liste von History-Dicts mit 'path' und 'timestamp'.

        Returns:
            Liste von (pfad, anzeigetext) Tuples mit Icon und Timestamp.
        """
        items = []
        for entry in history:
            path = entry["path"]
            timestamp = datetime.fromisoformat(entry["timestamp"]).strftime(
                "%Y-%m-%d %H:%M"
            )
            path_obj = Path(path)
            if path_obj.is_file():
                icon = "📄"
            elif path_obj.is_dir():
                icon = "📁"
            else:
                icon = "❓"  # Pfad existiert nicht mehr
            items.append((path, f"{icon} {path} ({timestamp})"))
        return items

    def _get_first_history_path(self, history_type: str) -> Path | None:
        """Liefert den Pfad des ersten History-Eintrags des angegebenen Typs.

        Args:
            history_type: "export" oder "import".

        Returns:
            Pfad des neuesten Eintrags dieses Typs (Alt-Einträge ohne type-Feld
            zählen für beide Typen) oder None wenn keiner existiert.
        """
        self.config_manager.reload()
        history = self.config_manager.config.get("history", [])
        # Alt-Einträge ohne type-Feld gelten für beide Typen
        entry = next(
            (h for h in history if h.get("type", history_type) == history_type), None
        )
        if entry is None:
            return None
        return Path(entry["path"]).expanduser()

    def handle_export_first(self) -> None:
        """Export per Hotkey zum ersten Export-Eintrag der History."""
        destination = self._get_first_history_path("export")
        if destination is None:
            curses.wrapper(
                curses_message, "Export", "Kein Export-Eintrag in der History"
            )
            return

        self.handle_export(destination)

    def handle_import_first(self) -> None:
        """Import per Hotkey vom ersten Import-Eintrag der History."""
        source = self._get_first_history_path("import")
        if source is None:
            curses.wrapper(
                curses_message, "Import", "Kein Import-Eintrag in der History"
            )
            return
        self.handle_import(source)

    def handle_open_import_source(self) -> None:
        """Öffnet den ersten Import-Eintrag der History in VS Code."""
        source = self._get_first_history_path("import")
        if source is None:
            curses.wrapper(
                curses_message, "VS Code", "Kein Import-Eintrag in der History"
            )
            return
        if not source.exists():
            curses.wrapper(curses_message, "VS Code", f"Pfad existiert nicht: {source}")
            return
        try:
            subprocess.run([VSCODE_BINARY, str(source)])
        except FileNotFoundError:
            curses.wrapper(
                curses_message,
                "VS Code",
                "code-Kommando nicht gefunden – in VS Code "
                "„Shell Command: Install 'code' command in PATH“ ausführen",
            )

    def handle_reset(self) -> None:
        """Reset-Operation mit Bestätigung."""
        if self.workspace_manager.is_empty():
            return

        confirm = curses.wrapper(
            curses_confirm,
            "Alle Daten im Workspace werden gelöscht!\nFortfahren?",
            default=False,
            mouse_enabled=self._is_mouse_navigation_enabled(),
        )
        if confirm:
            if self.workspace_manager.reset():
                self.config_manager.record_reset()

    def _confirm_export_target(self, destination: Path) -> bool:
        """Warnt wenn destination vom letzten Import-Pfad abweicht.

        Verhindert versehentliche Exporte in ein fremdes Projekt (Folder-Export
        hat Mirror-Semantik, überträgt also auch Löschungen).

        Args:
            destination: Aufgelöstes Export-Ziel.

        Returns:
            True wenn fortgefahren werden soll (Ziel entspricht dem Import oder
            User bestätigt trotz Abweichung), sonst False.
        """
        import_path = self._get_first_history_path("import")
        if import_path == destination:
            return True
        import_str = str(import_path) if import_path else "(kein Import-Eintrag)"
        return curses.wrapper(
            curses_confirm,
            "Export-Ziel weicht vom letzten Import ab!\n"
            f"Export: {destination}\n"
            f"Import: {import_str}\n"
            "Wirklich exportieren?",
            default=False,
            mouse_enabled=self._is_mouse_navigation_enabled(),
        )

    def handle_export(self, destination: Path | None = None) -> None:
        """Export-Operation mit Auto-Detect: Single File oder Folder.

        Args:
            destination: Optionales Ziel; None öffnet die Pfad-Auswahl.
        """
        self.config_manager.reload()
        if self.workspace_manager.is_empty():
            curses.wrapper(
                curses_message, "Export", "Workspace ist leer, nichts zu exportieren"
            )
            return

        destination = (
            destination or self.export_path or self.select_path_with_history("export")
        )
        if destination is None:
            return

        if not self._confirm_export_target(destination):
            return

        # Single File: Dateiendung vorhanden ODER Ziel ist bereits eine Datei
        # (Folder Mode: kein Suffix und kein existierender File-Pfad)
        if destination.suffix != "" or destination.is_file():
            self._handle_single_file_export(destination)
        else:
            success = self.workspace_manager.export_to(destination)
            if success:
                self.config_manager.add_to_history(destination, "export")

    def _handle_single_file_export(self, destination: Path) -> None:
        """Exportiert eine einzelne Datei aus Workspace – Dateiname aus Zielpfad.

        Args:
            destination: Zieldatei-Pfad; Dateiname bestimmt gesuchte Quelldatei.
        """
        filename = destination.name
        matches = [
            item
            for item in self.workspace_manager.workspace.rglob(filename)
            if item.is_file()
        ]

        if not matches:
            curses.wrapper(
                curses_message,
                "Export",
                f"Datei '{filename}' nicht in Workspace gefunden.",
            )
            return

        source_file = matches[0]
        rel_path = str(source_file.relative_to(self.workspace_manager.workspace))

        if destination.exists():
            dont_ask = self.config_manager.config.get(
                "dont_ask_on_export_overwrite", False
            )
            if not dont_ask:
                overwrite = curses.wrapper(
                    curses_confirm,
                    f"Die Zieldatei ({destination}) existiert bereits.\nÜberschreiben?",
                    default=False,
                    mouse_enabled=self._is_mouse_navigation_enabled(),
                )
                if not overwrite:
                    return

        success = self.workspace_manager.export_file_to(rel_path, destination)
        if success:
            self.config_manager.add_to_history(destination, "export")

    def handle_import(self, source: Path | None = None) -> None:
        """Import-Operation mit Auto-Detect: Single File oder Folder.

        Args:
            source: Optionale Quelle; None öffnet die Pfad-Auswahl.
        """
        self.config_manager.reload()
        source = source or self.import_path or self.select_path_with_history("import")
        if source is None:
            return

        if source.is_file():
            success = self.workspace_manager.import_file_from(source)
            if success:
                self.config_manager.add_to_history(source, "import")
        elif source.is_dir():
            success = self.workspace_manager.import_from(source)
            if success:
                self.config_manager.add_to_history(source, "import")
        else:
            curses.wrapper(curses_message, "Fehler", f"Pfad existiert nicht:\n{source}")

    def launch_claude(self) -> bool:
        """Startet Claude als Subprocess, kehrt zum Menü zurück nach Exit.

        Returns:
            True (Menü-Loop fortsetzen).
        """
        if not self.claude_binary.exists():
            print(f"✗ Claude Binary nicht gefunden: {self.claude_binary}")
            return True

        try:
            subprocess.run(["/usr/bin/clear"], check=False)
            self._apply_macos_theme()

            env = os.environ.copy()
            env.update(self.config_manager.config.get("claude_env", {}))

            cmd = [str(self.claude_binary)]

            instruction = self.config_manager.config.get(
                "claude_instruction", ""
            ).strip()
            if instruction:
                cmd.extend(["--", instruction])

            result = subprocess.run(
                cmd,
                cwd=str(self.workspace_manager.workspace),
                env=env,
                check=False,
            )
            print(f"\nClaude wurde beendet (Exit Code: {result.returncode})")
        except (OSError, subprocess.SubprocessError) as e:
            print(f"✗ Fehler beim Starten von Claude: {e}")

        return True

    def _apply_macos_theme(self) -> None:
        """Setzt Claude-Theme basierend auf macOS Dark/Light Mode.

        Liest den macOS-Interfacestil via `defaults` CLI und schreibt `theme`
        in ~/.claude.json. Bei korrupter JSON-Datei wird sie überschrieben.
        """
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
        )
        # Kein Output = Light Mode (macOS Standard wenn kein Dark Mode aktiv)
        theme = "dark" if result.stdout.strip() == "Dark" else "light"

        claude_json_path = Path.home() / ".claude.json"
        settings: dict[str, Any] = {}
        if claude_json_path.exists():
            try:
                with open(claude_json_path, "r") as f:
                    settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}

        settings["theme"] = theme
        with open(claude_json_path, "w") as f:
            json.dump(settings, f, indent=2)

    def handle_browse(self) -> None:
        """Zeigt Workspace-Inhalt in scrollbarer Ansicht."""
        self.config_manager.reload()
        contents = self.workspace_manager.get_contents()
        status = self.workspace_manager.get_status()
        summary = f"{status['file_count']} Dateien | {status['size_mb']} MB"
        curses.wrapper(
            curses_browse,
            "📂 Workspace Inhalt",
            summary,
            contents,
            self._is_mouse_navigation_enabled(),
        )

    def handle_plan(self) -> None:
        """Öffnet Plan.md im Workspace mit vi (wird erstellt falls nicht vorhanden)."""
        plan_file = self.workspace_manager.workspace / "Plan.md"
        subprocess.run(["vi", str(plan_file)])

    def handle_shell(self) -> None:
        """Öffnet eine Login-Shell im Workspace-Verzeichnis."""
        shell = os.environ.get("SHELL", DEFAULT_SHELL)
        subprocess.run([shell, "-l"], cwd=str(self.workspace_manager.workspace))

    def handle_action(self, action: str) -> tuple[bool, bool]:
        """Führt Menü-Aktion aus.

        Args:
            action: Action-Key aus get_menu_items().

        Returns:
            Tuple (continue_loop, wait_for_enter).
        """
        shortcut = ACTION_TO_SHORTCUT.get(action)
        if shortcut is not None:
            self.config_manager.record_shortcut_usage(shortcut)

        if action == "reset":
            self.handle_reset()
        elif action == "start":
            self.launch_claude()
        elif action == "export":
            self.handle_export()
        elif action == "import":
            self.handle_import()
        elif action == "export_first":
            self.handle_export_first()
        elif action == "import_first":
            self.handle_import_first()
        elif action == "open_import_source":
            self.handle_open_import_source()
        elif action == "browse":
            self.handle_browse()
        elif action == "plan":
            self.handle_plan()
        elif action == "shell":
            self.handle_shell()
        elif action == "quit":
            return (False, False)

        return (True, False)

    def run(self) -> None:
        """Hauptschleife: Direkt-Modus oder interaktiver Menü-Loop."""
        try:
            if self.export_path:
                self.handle_export()
                return

            if self.import_path:
                self.handle_import()
                return

            while True:
                status = self.workspace_manager.get_status()
                menu_items = self.get_menu_items()
                status_text = self._build_status_text(status)
                default_index = self._get_default_menu_index(menu_items)
                idle_timeout_ms = self._get_plan_idle_timer_interval_ms()
                usage_stats_text = self._build_usage_stats_text(self._get_cached_usage_stats())
                mouse_enabled = self._is_mouse_navigation_enabled()

                try:
                    result = curses.wrapper(
                        curses_menu,
                        "Claude Code Launcher",
                        status_text,
                        menu_items,
                        default_index,
                        idle_timeout_ms,
                        self._plan_swap_file_exists,
                        usage_stats_text,
                        mouse_enabled,
                    )
                except KeyboardInterrupt:
                    print("\nAuf Wiedersehen!")
                    break
                except (RuntimeError, curses.error) as e:
                    print(f"✗ Interaktives Menü nicht verfügbar: {e}")
                    print(
                        "Bitte verwende --export oder --import für nicht-interaktive Nutzung"
                    )
                    break

                if result is None:
                    print("Auf Wiedersehen!")
                    break

                if self._handle_sentinel(result):
                    continue

                continue_loop, wait_for_enter = self.handle_action(result)

                if not continue_loop:
                    break

                if wait_for_enter:
                    input("\nDrücke Enter um fortzufahren...")

        except KeyboardInterrupt:
            print("\nAbgebrochen durch Benutzer")
        except Exception as e:
            print(f"✗ Unerwarteter Fehler: {e}")
            raise


def main() -> None:
    """Haupteinstiegspunkt."""
    # Reduzierter Start-PATH würde sonst an alle Subprozesse vererbt
    login_path = _load_login_shell_path()
    if login_path:
        os.environ["PATH"] = login_path

    parser = argparse.ArgumentParser(
        description="Claude Code Launcher - Interaktiver Session Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s /path/to/.claude                     # Verwendet angegebenes Workspace
  %(prog)s /path/to/.claude --export /backup    # Exportiert direkt zu angegebenem Pfad
  %(prog)s /path/to/.claude --import /backup    # Importiert direkt von angegebenem Pfad
  %(prog)s /path/to/.claude --config custom.toml # Verwendet eigene Config-Datei
        """,
    )
    parser.add_argument("workspace", help="Pfad zum Workspace Verzeichnis (REQUIRED)")
    parser.add_argument(
        "--export",
        dest="export_path",
        metavar="PATH",
        help="Exportiert Workspace direkt zum angegebenen Pfad",
    )
    parser.add_argument(
        "--import",
        dest="import_path",
        metavar="PATH",
        help="Importiert Workspace direkt vom angegebenen Pfad",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Pfad zur Config-Datei (default: ./config.toml)",
    )
    parser.add_argument(
        "--claude-binary",
        default=None,
        help="Pfad zum Claude Binary (default: automatische Erkennung via PATH)",
    )

    args = parser.parse_args()

    if args.claude_binary:
        claude_binary = Path(args.claude_binary)
    else:
        claude_path = shutil.which("claude")
        if claude_path:
            claude_binary = Path(claude_path)
        else:
            print("✗ Claude Binary nicht gefunden im PATH")
            print(
                "Bitte installiere Claude Code oder gib den Pfad mit --claude-binary an"
            )
            sys.exit(1)

    workspace = Path(args.workspace).absolute()
    config_manager = ConfigManager(Path(args.config) if args.config else None)

    # Prüfen ob Workspace existiert, BEVOR ncurses startet
    if not workspace.exists():
        print(f"Workspace existiert nicht: {workspace}")
        response = input("Möchten Sie das Workspace-Verzeichnis anlegen? (j/n): ")
        if response.lower() in ["j", "y", "ja", "yes"]:
            workspace.mkdir(parents=True, exist_ok=True)
            print(f"✓ Workspace erstellt: {workspace}\n")
        else:
            print("Abgebrochen. Workspace wurde nicht erstellt.")
            sys.exit(0)

    export_path = Path(args.export_path).absolute() if args.export_path else None
    import_path = Path(args.import_path).absolute() if args.import_path else None

    app = LauncherApp(
        workspace,
        config_manager,
        claude_binary,
        export_path=export_path,
        import_path=import_path,
    )
    app.run()


if __name__ == "__main__":
    main()
