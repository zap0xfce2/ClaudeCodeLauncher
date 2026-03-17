#!/usr/bin/env python3
"""Claude Code Launcher - Session Management Tool für ClaudeHome"""

VERSION = "vYYMMDD"

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


def _init_curses_colors(stdscr: "curses.window") -> None:
    """Initialisiert alle Curses Farb-Paare einmalig.

    Args:
        stdscr: Das Curses Hauptfenster.
    """
    curses.init_pair(COLOR_PAIR_CYAN, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(COLOR_PAIR_YELLOW, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(COLOR_PAIR_GREEN, curses.COLOR_GREEN, curses.COLOR_BLACK)


def curses_menu(
    stdscr: "curses.window",
    banner_text: str,
    status_text: str,
    menu_items: list[tuple[str, str]],
    default_index: int = 0,
) -> str | None:
    """Zeigt Hauptmenü mit Banner oben, Menü links und Status-Info rechts.

    Args:
        stdscr: Das Curses Hauptfenster.
        banner_text: Titel oben links.
        status_text: Mehrzeiliger Status; letzte Zeile = Footer, Rest = Info rechts.
        menu_items: Liste von (action_key, label) Tuples.
        default_index: Vorausgewählter Menü-Index.

    Returns:
        Action-Key des gewählten Eintrags, Sentinel-String oder None bei Abbruch.
    """
    curses.curs_set(0)
    _init_curses_colors(stdscr)
    current = default_index

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

        if key == curses.KEY_UP or key == ord("k") or key == curses.KEY_BTAB:
            current = (current - 1) % len(menu_items)
        elif key == curses.KEY_DOWN or key == ord("j") or key == KEY_TAB:
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
    curses.curs_set(0)
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
            current = 1 - current  # Toggle zwischen Ja und Nein
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
    curses.curs_set(1)
    _init_curses_colors(stdscr)
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
        stdscr.addstr(y, 4, user_input + " " * (width - len(user_input) - 6))
        stdscr.move(y, 4 + cursor_pos)
        stdscr.refresh()

        key = stdscr.getch()

        if key == ord("\n"):
            curses.curs_set(0)
            return user_input
        elif key == KEY_ESC:
            curses.curs_set(0)
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
    curses.curs_set(0)
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
                    4,
                    f"> {label}",
                    curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(y, 4, f"  {label}")

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

        if key == curses.KEY_UP or key == ord("k") or key == curses.KEY_BTAB:
            current = (current - 1) % len(items)
        elif (
            key == curses.KEY_DOWN
            or key == ord("j")
            or (key == KEY_TAB and not allow_edit)
        ):
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
    curses.curs_set(0)
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
        stdscr.addstr(4, 4, "Keine Dateien vorhanden.")
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
                    4,
                    f"> {display}",
                    curses.color_pair(COLOR_PAIR_CYAN) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(y, 4, f"  {display}")

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

        if key == curses.KEY_UP or key == ord("k") or key == curses.KEY_BTAB:
            current = (current - 1) % len(items)
        elif key == curses.KEY_DOWN or key == ord("j") or key == KEY_TAB:
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
    curses.curs_set(0)
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

    def load_config(self) -> dict:
        """Lädt Config oder erstellt Default falls nicht vorhanden.

        Returns:
            Config-Dictionary mit allen Einstellungen.
        """
        default_config = {
            "history": [],
            "max_history_entries": 10,
            "export_ignore_patterns": [],
            "import_ignore_patterns": [],
            "claude_env": {},
            "ask_for_reset": True,
            "dont_ask_on_export_overwrite": False,
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

    def save_config(self, config: dict | None = None) -> None:
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


class ClaudeHomeManager:
    """Verwaltet ClaudeHome-Operationen (Reset, Export, Import)."""

    def __init__(
        self,
        claude_home_path: Path,
        config_manager: "ConfigManager | None" = None,
    ):
        """Initialisiert den ClaudeHomeManager.

        Args:
            claude_home_path: Pfad zum ClaudeHome-Verzeichnis.
            config_manager: Optionaler ConfigManager für Ignore-Patterns und Config-Zugriff.
        """
        self.claude_home = Path(claude_home_path)
        self.settings_file = self.claude_home / "settings.local.json"
        self.config_manager = config_manager

    def is_empty(self) -> bool:
        """Prüft ob ClaudeHome leer ist (ignoriert settings.local.json).

        Returns:
            True wenn keine relevanten Dateien vorhanden sind.
        """
        if not self.claude_home.exists():
            return True
        return not any(
            item.is_file() and item != self.settings_file
            for item in self.claude_home.rglob("*")
        )

    def get_status(self) -> dict:
        """Gibt Status zurück: Leer-Flag, Dateianzahl und Größe in MB.

        Returns:
            Dict mit Schlüsseln: is_empty, file_count, size_mb.
        """
        if self.is_empty():
            return {"is_empty": True, "file_count": 0, "size_mb": 0.0}

        file_count = 0
        total_size = 0
        for item in self.claude_home.rglob("*"):
            if item.is_file() and item != self.settings_file:
                file_count += 1
                total_size += item.stat().st_size

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
        if not self.claude_home.exists():
            return []

        entries = []
        for item in sorted(self.claude_home.rglob("*")):
            if not item.is_file():
                continue

            rel_path = str(item.relative_to(self.claude_home))
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
        """Löscht alle Einträge in ClaudeHome oder erstellt es neu."""
        if self.claude_home.exists():
            for item in self.claude_home.iterdir():
                self._delete_item(item)
        else:
            self.claude_home.mkdir(parents=True, exist_ok=True)

    def _get_ignore_arg(self, pattern_key: str):
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
        """Löscht ClaudeHome vollständig (alle Dateien und Verzeichnisse).

        Returns:
            True bei Erfolg, False bei Fehler.
        """
        try:
            self._clear_directory()
            print("✓ ClaudeHome erfolgreich zurückgesetzt")
            return True
        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except OSError as e:
            print(f"✗ Fehler beim Reset: {e}")
            return False

    def export_to(self, destination: Path) -> bool:
        """Exportiert ClaudeHome zu Ziel-Pfad (Folder Mode).

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
            kwargs: dict = {"dirs_exist_ok": True}
            if ignore_arg:
                kwargs["ignore"] = ignore_arg
            shutil.copytree(self.claude_home, destination, **kwargs)

            print(f"✓ Erfolgreich exportiert nach: {destination}")

            ask_for_reset = (
                self.config_manager.config.get("ask_for_reset", True)
                if self.config_manager
                else True
            )
            if ask_for_reset:
                if curses.wrapper(
                    curses_confirm, "ClaudeHome jetzt zurücksetzen?", default=False
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
        """Exportiert eine einzelne Datei aus ClaudeHome nach destination.

        Args:
            rel_file_path: Relativer Pfad der Quelldatei innerhalb von ClaudeHome.
            destination: Zieldatei-Pfad.

        Returns:
            True bei Erfolg, False bei Fehler.
        """
        source_file = self.claude_home / rel_file_path

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
        for pattern in ignore_patterns:
            if fnmatch.fnmatch(source_file.name, pattern):
                curses.wrapper(
                    curses_message,
                    "Warnung",
                    f"Datei entspricht Ignore-Pattern '{pattern}'.\nExport wird trotzdem durchgeführt.",
                )
                break

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
        """Importiert eine einzelne Datei nach ClaudeHome-Root.

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
        for pattern in ignore_patterns:
            if fnmatch.fnmatch(source_file.name, pattern):
                curses.wrapper(
                    curses_message,
                    "Warnung",
                    f"Datei entspricht Ignore-Pattern '{pattern}'.\nImport wird trotzdem durchgeführt.",
                )
                break

        try:
            destination = self.claude_home / source_file.name
            shutil.copy2(source_file, destination)
            return True
        except PermissionError as e:
            curses.wrapper(curses_message, "Fehler", f"Keine Berechtigung:\n{e}")
            return False
        except OSError as e:
            curses.wrapper(curses_message, "Fehler", f"Fehler beim Import:\n{e}")
            return False

    def import_from(self, source: Path) -> bool:
        """Importiert ClaudeHome von Quell-Pfad (Folder Mode).

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
                    "Alle Daten im ClaudeHome werden beim Import gelöscht!\nFortfahren?",
                    default=False,
                )
                if not confirm:
                    return False

            self._clear_directory()

            ignore_arg = self._get_ignore_arg("import_ignore_patterns")
            kwargs: dict = {"dirs_exist_ok": True}
            if ignore_arg:
                kwargs["ignore"] = ignore_arg
            shutil.copytree(source, self.claude_home, **kwargs)

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
        claude_home: Path,
        config_manager: ConfigManager,
        claude_binary: Path,
        export_path: Path | None = None,
        import_path: Path | None = None,
    ):
        """Initialisiert die LauncherApp.

        Args:
            claude_home: Pfad zum ClaudeHome-Verzeichnis.
            config_manager: ConfigManager-Instanz.
            claude_binary: Pfad zum Claude Binary.
            export_path: Optionaler Direkt-Export-Pfad (CLI-Argument).
            import_path: Optionaler Direkt-Import-Pfad (CLI-Argument).
        """
        self.config_manager = config_manager
        self.claude_home_manager = ClaudeHomeManager(claude_home, config_manager)
        self.claude_binary = Path(claude_binary)
        self.export_path = export_path
        self.import_path = import_path

    def get_menu_items(self) -> list[tuple[str, str]]:
        """Generiert Menü-Items basierend auf ClaudeHome-Status.

        Returns:
            Liste von (action_key, label) Tuples für das Hauptmenü.
        """
        is_empty = self.claude_home_manager.is_empty()
        items: list[tuple[str, str]] = []

        items.append(("plan", "📝 Plan schreiben"))

        if not is_empty:
            items.append(("export", "⤴️  Exportieren"))
            items.append(("browse", "📂 Inhalt von ClaudeHome anzeigen"))

        items.append(("import", "⤵️  Importieren"))

        if is_empty:
            items.append(("start", "▶️  Neue Sitzung starten"))
        else:
            items.append(("resume", "▶️  Sitzung fortsetzen"))

        items.append(("shell", "🖥️  Shell öffnen"))

        if not is_empty:
            items.append(("reset", "🔄 Reset"))

        return items

    def _build_status_text(self, status: dict) -> str:
        """Generiert den mehrzeiligen Status-String für das Hauptmenü.

        Args:
            status: Status-Dict von ClaudeHomeManager.get_status().

        Returns:
            Mehrzeiliger String: Info-Zeilen + Footer als letzte Zeile.
        """
        claude_home_path = str(self.claude_home_manager.claude_home)
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

        return f"📁 {claude_home_path}\n{content_line}\n{export_line}{footer}"

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
        if self.claude_home_manager.is_empty():
            return

        confirm = curses.wrapper(
            curses_confirm,
            "Alle Daten im ClaudeHome werden gelöscht!\nFortfahren?",
            default=False,
        )
        if confirm:
            if self.claude_home_manager.reset():
                self.config_manager.record_reset()

    def handle_export(self) -> None:
        """Export-Operation mit Auto-Detect: Single File oder Folder."""
        if self.claude_home_manager.is_empty():
            curses.wrapper(
                curses_message, "Export", "ClaudeHome ist leer, nichts zu exportieren"
            )
            return

        destination = self.export_path or self.select_path_with_history("export")
        if destination is None:
            return

        if destination.suffix != "" or destination.is_file():
            self._handle_single_file_export(destination)
        else:
            success = self.claude_home_manager.export_to(destination)
            if success:
                self.config_manager.add_to_history(destination, "export")

    def _handle_single_file_export(self, destination: Path) -> None:
        """Exportiert eine einzelne Datei aus ClaudeHome – Dateiname aus Zielpfad.

        Args:
            destination: Zieldatei-Pfad; Dateiname bestimmt gesuchte Quelldatei.
        """
        filename = destination.name
        matches = [
            item
            for item in self.claude_home_manager.claude_home.rglob(filename)
            if item.is_file()
        ]

        if not matches:
            curses.wrapper(
                curses_message,
                "Export",
                f"Datei '{filename}' nicht in ClaudeHome gefunden.",
            )
            return

        source_file = matches[0]
        rel_path = str(source_file.relative_to(self.claude_home_manager.claude_home))

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

        success = self.claude_home_manager.export_file_to(rel_path, destination)
        if success:
            self.config_manager.add_to_history(destination, "export")

    def handle_import(self) -> None:
        """Import-Operation mit Auto-Detect: Single File oder Folder."""
        source = self.import_path or self.select_path_with_history("import")
        if source is None:
            return

        if source.is_file():
            success = self.claude_home_manager.import_file_from(source)
            if success:
                self.config_manager.add_to_history(source, "import")
        elif source.is_dir():
            success = self.claude_home_manager.import_from(source)
            if success:
                self.config_manager.add_to_history(source, "import")
        else:
            curses.wrapper(curses_message, "Fehler", f"Pfad existiert nicht:\n{source}")

    def launch_claude(self, resume: bool) -> bool:
        """Startet Claude als Subprocess, kehrt zum Menü zurück nach Exit.

        Args:
            resume: True für Session-Resume, False für neue Session.

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

            result = subprocess.run(
                [str(self.claude_binary)],
                cwd=str(self.claude_home_manager.claude_home),
                env=env,
            )
            print(f"\nClaude wurde beendet (Exit Code: {result.returncode})")
        except (OSError, subprocess.SubprocessError) as e:
            print(f"✗ Fehler beim Starten von Claude: {e}")

        return True

    def _apply_macos_theme(self) -> None:
        """Setzt Claude-Theme basierend auf macOS Dark/Light Mode."""
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
        )
        # Kein Output = Light Mode (macOS Standard wenn kein Dark Mode aktiv)
        theme = "dark" if result.stdout.strip() == "Dark" else "light"

        claude_json_path = Path.home() / ".claude.json"
        settings: dict = {}
        if claude_json_path.exists():
            try:
                with open(claude_json_path, "r") as f:
                    settings = json.load(f)
            except (json.JSONDecodeError, ValueError):
                settings = {}

        settings["theme"] = theme
        with open(claude_json_path, "w") as f:
            json.dump(settings, f, indent=2)

    def handle_browse(self) -> None:
        """Zeigt ClaudeHome-Inhalt in scrollbarer Ansicht."""
        contents = self.claude_home_manager.get_contents()
        status = self.claude_home_manager.get_status()
        summary = f"{status['file_count']} Dateien | {status['size_mb']} MB"
        curses.wrapper(curses_browse, "📂 ClaudeHome Inhalt", summary, contents)

    def handle_plan(self) -> None:
        """Öffnet oder erstellt Plan.md im ClaudeHome mit vi."""
        plan_file = self.claude_home_manager.claude_home / "Plan.md"
        subprocess.run(["vi", str(plan_file)])

    def handle_shell(self) -> None:
        """Öffnet eine Shell im ClaudeHome-Verzeichnis."""
        shell = os.environ.get("SHELL", "/bin/zsh")
        subprocess.run([shell], cwd=str(self.claude_home_manager.claude_home))

    def handle_action(self, action: str) -> tuple[bool, bool]:
        """Führt Menü-Aktion aus.

        Args:
            action: Action-Key aus get_menu_items().

        Returns:
            Tuple (continue_loop, wait_for_enter).
        """
        if action == "reset":
            self.handle_reset()
        elif action in ("start", "resume"):
            self.launch_claude(action == "resume")
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
                status = self.claude_home_manager.get_status()
                menu_items = self.get_menu_items()
                status_text = self._build_status_text(status)

                try:
                    result = curses.wrapper(
                        curses_menu, "Claude Code Launcher", status_text, menu_items, 0
                    )
                except KeyboardInterrupt:
                    print("\nAuf Wiedersehen!")
                    break
                except Exception as e:
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
  %(prog)s /path/to/.claude                     # Verwendet angegebenes ClaudeHome
  %(prog)s /path/to/.claude --export /backup    # Exportiert direkt zu angegebenem Pfad
  %(prog)s /path/to/.claude --import /backup    # Importiert direkt von angegebenem Pfad
  %(prog)s /path/to/.claude --config custom.yaml # Verwendet eigene Config-Datei
        """,
    )
    parser.add_argument(
        "claude_home", help="Pfad zum ClaudeHome Verzeichnis (REQUIRED)"
    )
    parser.add_argument(
        "--export",
        dest="export_path",
        metavar="PATH",
        help="Exportiert ClaudeHome direkt zum angegebenen Pfad",
    )
    parser.add_argument(
        "--import",
        dest="import_path",
        metavar="PATH",
        help="Importiert ClaudeHome direkt vom angegebenen Pfad",
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

    claude_home = Path(args.claude_home).absolute()
    config_manager = ConfigManager(Path(args.config) if args.config else None)

    # Prüfen ob ClaudeHome existiert, BEVOR ncurses startet
    if not claude_home.exists():
        print(f"ClaudeHome existiert nicht: {claude_home}")
        response = input("Möchten Sie das ClaudeHome-Verzeichnis anlegen? (j/n): ")
        if response.lower() in ["j", "y", "ja", "yes"]:
            claude_home.mkdir(parents=True, exist_ok=True)
            print(f"✓ ClaudeHome erstellt: {claude_home}\n")
        else:
            print("Abgebrochen. ClaudeHome wurde nicht erstellt.")
            sys.exit(0)

    export_path = Path(args.export_path).absolute() if args.export_path else None
    import_path = Path(args.import_path).absolute() if args.import_path else None

    app = LauncherApp(
        claude_home,
        config_manager,
        claude_binary,
        export_path=export_path,
        import_path=import_path,
    )
    app.run()


if __name__ == "__main__":
    main()
