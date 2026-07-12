#!/usr/bin/env python3
"""Claude Code Launcher - Session Management Tool für Workspace"""

VERSION = "vYYMMDDhhmm"

import fnmatch
import json
import os
import shutil
import sys
import argparse
import yaml
import curses
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Literal, overload
from collections.abc import Callable

# --- Curses Farb-Paar IDs ---
COLOR_PAIR_CYAN = 1
COLOR_PAIR_YELLOW = 2
COLOR_PAIR_GREEN = 3

# --- Key Codes ---
KEY_TAB = 9
KEY_ESC = 27
KEY_BACKSPACE_DEL = 127
KEY_SPACE = 32
KEY_PRINTABLE_MAX = 126

# --- UI Layout ---
MENU_TITLE_ROW = 1
MENU_SEPARATOR_ROW = 2
MENU_START_ROW = 4
UI_PADDING_X = 2
MENU_RIGHT_COL_BUFFER = 18

# --- Dateigrößen ---
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024

# --- Plan-Idle-Timer ---
MILLISECONDS_PER_SECOND = 1000
DEFAULT_PLAN_IDLE_TIMER_DURATION = 10

# --- Einrückung für Listen-Einträge (UI_PADDING_X + "> " Präfix) ---
ITEM_INDENT_X = UI_PADDING_X + 2  # = 4


def _init_curses_colors(stdscr: "curses.window") -> None:
    """Initialisiert alle Curses Farb-Paare und setzt Cursor einmalig.

    Args:
        stdscr: Das Curses Hauptfenster.
    """
    curses.curs_set(0)
    curses.init_pair(COLOR_PAIR_CYAN, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(COLOR_PAIR_YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(COLOR_PAIR_GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)


def _is_up_key(key: int) -> bool:
    """Prüft ob key eine Aufwärts-Navigation auslöst.

    Args:
        key: Curses-Tastencode.

    Returns:
        True für KEY_UP, k oder Shift+Tab.
    """
    return key in (curses.KEY_UP, ord("k"), curses.KEY_BTAB)


def _is_down_key(key: int, include_tab: bool = True) -> bool:
    """Prüft ob key eine Abwärts-Navigation auslöst.

    Args:
        key: Curses-Tastencode.
        include_tab: Ob Tab als Abwärts-Taste gilt (Standard: True).

    Returns:
        True für KEY_DOWN, j oder (wenn include_tab) Tab.
    """
    return key in (curses.KEY_DOWN, ord("j")) or (include_tab and key == KEY_TAB)


def curses_menu(
    stdscr: "curses.window",
    banner_text: str,
    status_text: str,
    menu_items: list[tuple[str, str]],
    default_index: int = 0,
    idle_timeout_ms: int | None = None,
    idle_refresh_predicate: Callable[[], bool] | None = None,
) -> str | None:
    """Zeigt Hauptmenü mit Banner oben, Menü links und Status-Info rechts.

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

    Returns:
        Action-Key des gewählten Eintrags, Sentinel-String oder None bei Abbruch.
    """
    _init_curses_colors(stdscr)
    current = default_index

    if idle_timeout_ms is not None:
        stdscr.timeout(idle_timeout_ms)

    initial_predicate_state = (
        idle_refresh_predicate() if idle_refresh_predicate is not None else None
    )

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Status-Text aufteilen: letzte Zeile = Footer, Rest = Info-Zeilen
        status_lines = status_text.split("\n")
        footer = status_lines[-1].strip() if status_lines else ""
        info_lines = [line.strip() for line in status_lines[:-1]]

        # Rechte Spalte dynamisch: längster Label + Prefix + Puffer für Emoji + Abstand
        max_label_len = max(len(label) for _, label in menu_items) if menu_items else 20
        right_col = UI_PADDING_X + 2 + max_label_len + MENU_RIGHT_COL_BUFFER

        # Titel links, Versionsnummer rechts
        stdscr.addstr(
            MENU_TITLE_ROW,
            UI_PADDING_X,
            banner_text,
            curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
        )
        version_x = width - len(VERSION) - UI_PADDING_X
        if version_x > len(banner_text) + 4:
            stdscr.addstr(MENU_TITLE_ROW, version_x, VERSION)

        # Separator
        sep = "─" * (width - 4)
        stdscr.addstr(
            MENU_SEPARATOR_ROW, UI_PADDING_X, sep, curses.color_pair(COLOR_PAIR_CYAN)
        )

        # Menü (links)
        for i, (_, label) in enumerate(menu_items):
            y = MENU_START_ROW + i
            if y >= height - 2:
                break
            if i == current:
                stdscr.addstr(
                    y,
                    UI_PADDING_X,
                    f"> {label}",
                    curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(y, UI_PADDING_X, f"  {label}")

        # Status-Info (rechts, neben den ersten Menü-Zeilen)
        for i, line in enumerate(info_lines):
            y = MENU_START_ROW + i
            if y >= height - 2 or right_col >= width:
                break
            max_len = width - right_col - UI_PADDING_X
            stdscr.addstr(
                y, right_col, line[:max_len], curses.color_pair(COLOR_PAIR_YELLOW)
            )

        # Footer (unterste Zeile, kein Rahmen)
        if height > 3:
            max_footer = width - 4
            stdscr.addstr(
                height - 2,
                UI_PADDING_X,
                footer[:max_footer],
                curses.color_pair(COLOR_PAIR_YELLOW),
            )

        stdscr.refresh()

        key = stdscr.getch()

        if key == -1:
            if (
                idle_refresh_predicate is None
                or idle_refresh_predicate() != initial_predicate_state
            ):
                return "__refresh__"
            continue
        elif _is_up_key(key):
            current = (current - 1) % len(menu_items)
        elif _is_down_key(key):
            current = (current + 1) % len(menu_items)
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
        elif key == ord("s"):
            return "shell"


def curses_confirm(
    stdscr: "curses.window",
    message: str,
    default: bool = False,
) -> bool:
    """Zeigt Ja/Nein Dialog.

    Args:
        stdscr: Das Curses Hauptfenster.
        message: Anzuzeigende Frage (kann Zeilenumbrüche enthalten).
        default: True wenn Ja vorausgewählt sein soll.

    Returns:
        True für Ja, False für Nein oder Abbruch.
    """
    _init_curses_colors(stdscr)
    current = 0 if default else 1
    choices = ["Ja", "Nein"]

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
                curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD,
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
                curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
            )
        else:
            stdscr.addstr(
                y,
                choice_x + len(f"> {choices[0]}") + 2,
                f"> {choices[1]}",
                curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
            )

        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_LEFT or key == ord("h"):
            current = 0
        elif key == curses.KEY_RIGHT or key == ord("l"):
            current = 1
        elif key == KEY_TAB:
            current ^= 1  # Toggle zwischen Ja (0) und Nein (1)
        elif key == ord("\n") or key == KEY_SPACE:
            return current == 0
        elif key == ord("y") or key == ord("j"):  # j=ja (Deutsch), y=yes (Englisch)
            return True
        elif key == ord("n"):
            return False
        elif key == KEY_ESC:
            return False


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
        y - 2, UI_PADDING_X, prompt, curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD
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
) -> tuple[str | None, bool]: ...


@overload
def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int = ...,
    allow_edit: Literal[False] = ...,
) -> str | None: ...


def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int = 0,
    allow_edit: bool = False,
) -> tuple[str | None, bool] | str | None:
    """Auswahl-Dialog für Listen (z.B. History).

    Args:
        stdscr: Das Curses Hauptfenster.
        title: Überschrift des Dialogs.
        items: Liste von (value, label) Tuples.
        default_index: Vorausgewählter Index.
        allow_edit: Wenn True, gibt (value, edit_mode) zurück; Tab öffnet Editierdialog.

    Returns:
        Wenn allow_edit=False: Gewählter value-String oder None.
        Wenn allow_edit=True: Tuple (value, edit_mode) oder (None, False).
    """
    _init_curses_colors(stdscr)
    current = default_index

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        stdscr.addstr(
            2, UI_PADDING_X, title, curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD
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
                    curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(y, ITEM_INDENT_X, f"  {label}")

        # Hint-Zeile
        if allow_edit:
            hint = "[Enter] Auswählen  [Tab] Bearbeiten  [ESC] Abbrechen"
        else:
            hint = "[Enter] Auswählen  [ESC] Abbrechen"
        stdscr.addstr(
            height - 2, UI_PADDING_X, hint, curses.color_pair(COLOR_PAIR_YELLOW)
        )

        stdscr.refresh()

        key = stdscr.getch()

        if _is_up_key(key):
            current = (current - 1) % len(items)
        elif _is_down_key(key, include_tab=not allow_edit):
            current = (current + 1) % len(items)
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


def curses_browse(
    stdscr: "curses.window",
    title: str,
    summary: str,
    items: list[tuple[str, str]],
) -> None:
    """Scrollbare Read-Only-Ansicht für Dateilisten.

    Args:
        stdscr: Das Curses Hauptfenster.
        title: Überschrift der Ansicht.
        summary: Zusammenfassung (Dateianzahl, Gesamtgröße).
        items: Liste von (value, label) Tuples zum Anzeigen.
    """
    _init_curses_colors(stdscr)
    height, width = stdscr.getmaxyx()

    # Guard-Clause für zu kleine Terminals
    if height < 8 or width < 40:
        stdscr.addstr(0, 0, "Terminal zu klein!")
        stdscr.getch()
        return

    current = 0

    if not items:
        stdscr.addstr(
            2, UI_PADDING_X, title, curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD
        )
        stdscr.addstr(MENU_START_ROW, ITEM_INDENT_X, "Keine Dateien vorhanden.")
        stdscr.addstr(
            height - 2, UI_PADDING_X, "ESC Zurück", curses.color_pair(COLOR_PAIR_YELLOW)
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
            1, UI_PADDING_X, title, curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD
        )
        stdscr.addstr(2, UI_PADDING_X, summary, curses.color_pair(COLOR_PAIR_YELLOW))

        # Scroll-Offset berechnen
        scroll_offset = (
            max(0, current - viewport_height + 1) if current >= viewport_height else 0
        )

        # Dateiliste rendern
        list_start_y = 4
        for i in range(viewport_height):
            idx = scroll_offset + i
            if idx >= len(items):
                break
            y = list_start_y + i
            if y >= height - 2:
                break
            _, label = items[idx]
            display = label[: width - 6]  # Auf Terminalbreite beschneiden
            if idx == current:
                stdscr.addstr(
                    y,
                    ITEM_INDENT_X,
                    f"> {display}",
                    curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(y, ITEM_INDENT_X, f"  {display}")

        # Position-Indikator und Hint
        pos_text = f"[{current + 1}/{len(items)}]"
        hint = "↑↓/j/k Navigieren | ESC Zurück"
        stdscr.addstr(
            height - 2, UI_PADDING_X, hint, curses.color_pair(COLOR_PAIR_YELLOW)
        )
        stdscr.addstr(
            height - 2,
            width - len(pos_text) - UI_PADDING_X,
            pos_text,
            curses.color_pair(COLOR_PAIR_YELLOW),
        )

        stdscr.refresh()

        key = stdscr.getch()

        if _is_up_key(key):
            current = (current - 1) % len(items)
        elif _is_down_key(key):
            current = (current + 1) % len(items)
        elif key == KEY_ESC:
            return


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
        curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
    )

    lines = message.split("\n")
    for i, line in enumerate(lines):
        stdscr.addstr(
            y + 2 + i,
            max(0, (width - len(line)) // 2),
            line,
            curses.color_pair(COLOR_PAIR_YELLOW),
        )

    hint = "[ Beliebige Taste drücken ]"
    stdscr.addstr(y + 2 + len(lines) + 1, max(0, (width - len(hint)) // 2), hint)
    stdscr.refresh()
    stdscr.getch()


class ConfigManager:
    """Verwaltet config.yaml mit Export/Import-History."""

    def __init__(self, config_path: Path | None = None):
        """Initialisiert den ConfigManager.

        Args:
            config_path: Pfad zur Config-Datei. Standardmäßig config.yaml im Script-Verzeichnis.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        self.config_path = Path(config_path)
        self.config = self.load_config()

    def load_config(self) -> dict[str, Any]:
        """Lädt Config oder erstellt Default falls nicht vorhanden.

        Returns:
            Config-Dictionary mit allen Einstellungen.

        Raises:
            yaml.YAMLError: Bei korrupter YAML-Datei (wird abgefangen, Backup erstellt).
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
        }

        if not self.config_path.exists():
            self.save_config(default_config)
            return default_config

        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f) or {}
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        except yaml.YAMLError as e:
            # Bei korrupter Config: Backup erstellen und Default verwenden
            print(f"Config-Datei korrupt: {e}")
            backup_path = self.config_path.with_suffix(".yaml.bak")
            if self.config_path.exists():
                shutil.copy(self.config_path, backup_path)
            return default_config

    def save_config(self, config: dict[str, Any] | None = None) -> None:
        """Speichert Config in YAML.

        Args:
            config: Zu speicherndes Dictionary. Wenn None, wird self.config verwendet.
        """
        if config is None:
            config = self.config

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(
                config, f, default_flow_style=False, allow_unicode=True, sort_keys=False
            )

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

        history = self.config["history"]
        path_str = str(path.absolute())

        # Duplikate entfernen, dann neuen Eintrag vorne einfügen
        history = [h for h in history if h.get("path") != path_str]
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
            Liste der History-Einträge.

        Raises:
            ValueError: Wenn history_type ungültig ist.
        """
        if history_type not in ["export", "import"]:
            raise ValueError(f"Invalid history_type: {history_type}")
        return self.config.get("history", [])

    def record_reset(self) -> None:
        """Speichert aktuellen Zeitstempel als letzten Reset-Zeitpunkt."""
        self.config["last_reset_timestamp"] = datetime.now().isoformat()
        self.save_config()

    def toggle_bool_option(self, key: str) -> bool:
        """Negiert Bool-Wert in Config und speichert zurück.

        Args:
            key: Config-Schlüssel des Bool-Werts.

        Returns:
            Neuer Wert nach dem Toggle.
        """
        self.config[key] = not self.config.get(key, False)
        self.save_config()
        return self.config[key]


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

    def get_contents(self) -> list[tuple[str, str]]:
        """Gibt Dateiliste zurück: [(relative_path, display_label), ...].

        Returns:
            Sortierte Liste von (relativer_pfad, Anzeigetext) Tuples.
            settings.local.json wird mit 🔒 markiert.
        """
        if not self.workspace.exists():
            return []

        entries = []
        for item in sorted(self.workspace.rglob("*")):
            if not item.is_file():
                continue

            rel_path = str(item.relative_to(self.workspace))
            size = item.stat().st_size

            if size < BYTES_PER_KB:
                size_str = f"{size} B"
            elif size < BYTES_PER_MB:
                size_str = f"{size / BYTES_PER_KB:.1f} KB"
            else:
                size_str = f"{size / BYTES_PER_MB:.1f} MB"

            label = f"{rel_path}  ({size_str})"
            if item.name == "settings.local.json":
                label = f"🔒 {label}"

            entries.append((rel_path, label))

        return entries

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

    def _get_ignore_arg(self, pattern_key: str) -> Any | None:
        """Gibt shutil.ignore_patterns-Argument zurück, falls Patterns konfiguriert.

        Args:
            pattern_key: Config-Schlüssel für die Patterns.

        Returns:
            shutil.ignore_patterns(...) oder None.
        """
        patterns = (
            self.config_manager.config.get(pattern_key, [])
            if self.config_manager
            else []
        )
        return shutil.ignore_patterns(*patterns) if patterns else None

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
            f"Das Ziel ({destination}) existiert bereits.\nDateien hinzufügen / überschreiben?",
            default=False,
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

            ignore_arg = self._get_ignore_arg("export_ignore_patterns")
            kwargs: dict[str, Any] = {"dirs_exist_ok": True}
            if ignore_arg:
                kwargs["ignore"] = ignore_arg
            shutil.copytree(self.workspace, destination, **kwargs)

            print(f"✓ Erfolgreich exportiert nach: {destination}")

            ask_for_reset = (
                self.config_manager.config.get("ask_for_reset", True)
                if self.config_manager
                else True
            )
            if ask_for_reset:
                if curses.wrapper(
                    curses_confirm, "Workspace jetzt zurücksetzen?", default=False
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
                )
                if not confirm:
                    return False

            self._clear_directory()

            ignore_arg = self._get_ignore_arg("import_ignore_patterns")
            kwargs: dict[str, Any] = {"dirs_exist_ok": True}
            if ignore_arg:
                kwargs["ignore"] = ignore_arg
            shutil.copytree(source, self.workspace, **kwargs)

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
        ask_reset = self.config_manager.config.get("ask_for_reset", True)
        dont_ask_overwrite = self.config_manager.config.get(
            "dont_ask_on_export_overwrite", False
        )

        ask_reset_str = "Ja" if ask_reset else "Nein"
        # dont_ask_on_export_overwrite=True bedeutet NICHT fragen → "Nein" anzeigen
        overwrite_ask_str = "Nein" if dont_ask_overwrite else "Ja"

        footer = (
            f"  [r] Refresh  [x] Nach Export zurücksetzen: {ask_reset_str}"
            f"  [o] Überschreiben bestätigen: {overwrite_ask_str}  [q] Beenden"
        )

        all_history = self.config_manager.config.get("history", [])
        last_export = next((h for h in all_history if h.get("type") == "export"), None)
        last_reset_ts = self.config_manager.config.get("last_reset_timestamp")
        export_line = self._get_export_line(last_export, last_reset_ts)

        content_line = (
            "   (leer)"
            if status["is_empty"]
            else f"   {status['file_count']} Dateien · {status['size_mb']} MB"
        )

        return f"📁 {workspace_path}\n{content_line}\n{export_line}{footer}"

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
            return f"   Letzter Export: {export_ts.strftime('%d.%m.%Y %H:%M')}\n"
        return ""

    def _handle_sentinel(self, result: str) -> bool:
        """Verarbeitet Sentinel-Rückgaben aus dem Menü (Refresh, Toggle-Hotkeys).

        Args:
            result: Rückgabewert von curses_menu.

        Returns:
            True wenn ein Sentinel verarbeitet wurde (Loop soll fortgesetzt werden).
        """
        if result == "__refresh__":
            self.config_manager.config = self.config_manager.load_config()
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

            raw = curses.wrapper(curses_select, select_title, history_items, 0, True)
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

    def handle_reset(self) -> None:
        """Reset-Operation mit Bestätigung."""
        if self.workspace_manager.is_empty():
            return

        confirm = curses.wrapper(
            curses_confirm,
            "Alle Daten im Workspace werden gelöscht!\nFortfahren?",
            default=False,
        )
        if confirm:
            if self.workspace_manager.reset():
                self.config_manager.record_reset()

    def handle_export(self) -> None:
        """Export-Operation mit Auto-Detect: Single File oder Folder."""
        if self.workspace_manager.is_empty():
            curses.wrapper(
                curses_message, "Export", "Workspace ist leer, nichts zu exportieren"
            )
            return

        destination = self.export_path or self.select_path_with_history("export")
        if destination is None:
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
                )
                if not overwrite:
                    return

        success = self.workspace_manager.export_file_to(rel_path, destination)
        if success:
            self.config_manager.add_to_history(destination, "export")

    def handle_import(self) -> None:
        """Import-Operation mit Auto-Detect: Single File oder Folder."""
        source = self.import_path or self.select_path_with_history("import")
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
        contents = self.workspace_manager.get_contents()
        status = self.workspace_manager.get_status()
        summary = f"{status['file_count']} Dateien | {status['size_mb']} MB"
        curses.wrapper(curses_browse, "📂 Workspace Inhalt", summary, contents)

    def handle_plan(self) -> None:
        """Öffnet Plan.md im Workspace mit vi (wird erstellt falls nicht vorhanden)."""
        plan_file = self.workspace_manager.workspace / "Plan.md"
        subprocess.run(["vi", str(plan_file)])

    def handle_shell(self) -> None:
        """Öffnet eine Shell im Workspace-Verzeichnis."""
        shell = os.environ.get("SHELL", "/bin/zsh")
        subprocess.run([shell], cwd=str(self.workspace_manager.workspace))

    def handle_action(self, action: str) -> tuple[bool, bool]:
        """Führt Menü-Aktion aus.

        Args:
            action: Action-Key aus get_menu_items().

        Returns:
            Tuple (continue_loop, wait_for_enter).
        """
        if action == "reset":
            self.handle_reset()
        elif action == "start":
            self.launch_claude()
        elif action == "export":
            self.handle_export()
        elif action == "import":
            self.handle_import()
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

                try:
                    result = curses.wrapper(
                        curses_menu,
                        "Claude Code Launcher",
                        status_text,
                        menu_items,
                        default_index,
                        idle_timeout_ms,
                        self._plan_swap_file_exists,
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
    parser = argparse.ArgumentParser(
        description="Claude Code Launcher - Interaktiver Session Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s /path/to/.claude                     # Verwendet angegebenes Workspace
  %(prog)s /path/to/.claude --export /backup    # Exportiert direkt zu angegebenem Pfad
  %(prog)s /path/to/.claude --import /backup    # Importiert direkt von angegebenem Pfad
  %(prog)s /path/to/.claude --config custom.yaml # Verwendet eigene Config-Datei
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
        help="Pfad zur Config-Datei (default: ./config.yaml)",
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
