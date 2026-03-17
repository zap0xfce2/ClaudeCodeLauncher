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
from typing import Dict, List, Optional, Tuple


def curses_menu(
    stdscr, banner_text: str, status_text: str, menu_items: list, default_index: int = 0
):
    """Zeigt Menü mit Banner oben, Menü Mitte, Status unten"""
    curses.curs_set(0)
    stdscr.clear()
    current = default_index
    height, width = stdscr.getmaxyx()

    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Status-Text aufteilen: letzte Zeile = Footer, Rest = Info-Zeilen
        status_lines = status_text.split("\n")
        footer = status_lines[-1].strip() if status_lines else ""
        info_lines = [l.strip() for l in status_lines[:-1]]

        # Dynamisch: längster Label + Prefix ("> ") + Puffer für Emoji-Breite + Mindestabstand
        max_label_len = max(len(label) for _, label in menu_items) if menu_items else 20
        right_col = 2 + 2 + max_label_len + 18
        menu_start = 4  # Zeile 1=Titel, 2=Separator, 3=leer, 4=Menü-Start

        # Titel links, Versionsnummer rechts
        stdscr.addstr(1, 2, banner_text, curses.color_pair(1) | curses.A_BOLD)
        version_x = width - len(VERSION) - 2
        if version_x > len(banner_text) + 4:  # nur anzeigen wenn genug Platz
            stdscr.addstr(1, version_x, VERSION)

        # Separator
        sep = "─" * (width - 4)
        stdscr.addstr(2, 2, sep, curses.color_pair(1))

        # Menü (links)
        for i, (key, label) in enumerate(menu_items):
            y = menu_start + i
            if y >= height - 2:
                break
            if i == current:
                stdscr.addstr(y, 2, f"> {label}", curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addstr(y, 2, f"  {label}")

        # Status-Info (rechts, neben den ersten Menü-Zeilen)
        for i, line in enumerate(info_lines):
            y = menu_start + i
            if y >= height - 2 or right_col >= width:
                break
            max_len = width - right_col - 2
            stdscr.addstr(y, right_col, line[:max_len], curses.color_pair(2))

        # Footer (unterste Zeile, kein Rahmen)
        if height > 3:
            max_footer = width - 4
            stdscr.addstr(height - 2, 2, footer[:max_footer], curses.color_pair(2))

        stdscr.refresh()

        key = stdscr.getch()

        if (
            key == curses.KEY_UP or key == ord("k") or key == curses.KEY_BTAB
        ):  # Shift+Tab
            current = (current - 1) % len(menu_items)
        elif key == curses.KEY_DOWN or key == ord("j") or key == 9:  # Tab
            current = (current + 1) % len(menu_items)
        elif key == ord("\n") or key == ord(" "):
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


def curses_confirm(stdscr, message: str, default: bool = False):
    """Zeigt Ja/Nein Dialog"""
    curses.curs_set(0)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    current = 0 if default else 1
    choices = ["Ja", "Nein"]

    while True:
        stdscr.clear()

        # Message (mehrzeilig und zentriert)
        lines = message.split("\n")
        start_y = height // 2 - len(lines) - 2

        for i, line in enumerate(lines):
            x = max(0, (width - len(line)) // 2)
            stdscr.addstr(
                start_y + i,
                x,
                line,
                curses.color_pair(2) | curses.A_BOLD,
            )

        # Choices
        y = start_y + len(lines) + 2
        choice_line = "  ".join(
            [f"> {c}" if i == current else f"  {c}" for i, c in enumerate(choices)]
        )
        stdscr.addstr(y, (width - len(choice_line)) // 2, choice_line)

        # Highlight current
        choice_x = (width - len(choice_line)) // 2
        if current == 0:
            stdscr.addstr(
                y, choice_x, f"> {choices[0]}", curses.color_pair(1) | curses.A_BOLD
            )
        else:
            stdscr.addstr(
                y,
                choice_x + len(f"> {choices[0]}") + 2,
                f"> {choices[1]}",
                curses.color_pair(1) | curses.A_BOLD,
            )

        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_LEFT or key == ord("h"):
            current = 0
        elif key == curses.KEY_RIGHT or key == ord("l"):
            current = 1
        elif key == 9:  # Tab
            current = 1 - current  # Toggle zwischen 0 und 1
        elif key == ord("\n") or key == ord(" "):
            return current == 0
        elif key == ord("j") or key == ord("n"):
            return False
        elif key == ord("y") or key == ord("j"):
            return True
        elif key == 27:
            return False


def curses_input(stdscr, prompt: str, default: str = ""):
    """Text-Eingabe Dialog"""
    curses.curs_set(1)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)

    y = height // 2
    stdscr.addstr(y - 2, 2, prompt, curses.color_pair(1) | curses.A_BOLD)
    stdscr.addstr(y, 2, "> ")

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
        elif key == 27:  # ESC
            curses.curs_set(0)
            return None
        elif key == curses.KEY_BACKSPACE or key == 127:
            if cursor_pos > 0:
                user_input = user_input[: cursor_pos - 1] + user_input[cursor_pos:]
                cursor_pos -= 1
        elif key == curses.KEY_LEFT:
            cursor_pos = max(0, cursor_pos - 1)
        elif key == curses.KEY_RIGHT:
            cursor_pos = min(len(user_input), cursor_pos + 1)
        elif 32 <= key <= 126:
            user_input = user_input[:cursor_pos] + chr(key) + user_input[cursor_pos:]
            cursor_pos += 1


def curses_select(
    stdscr, title: str, items: list, default_index: int = 0, allow_edit: bool = False
):
    """Auswahl-Dialog für Listen (z.B. History).

    Wenn allow_edit=True: gibt (value, edit_mode) zurück.
    e-Taste öffnet Editiermodus, Enter wählt direkt aus.
    """
    curses.curs_set(0)
    stdscr.clear()
    current = default_index
    height, width = stdscr.getmaxyx()

    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    while True:
        stdscr.clear()

        # Title
        stdscr.addstr(2, 2, title, curses.color_pair(1) | curses.A_BOLD)

        # Items (Platz für Hint-Zeile am Ende lassen)
        menu_start = 4
        for i, (value, label) in enumerate(items):
            y = menu_start + i
            if y >= height - 3:
                break
            if i == current:
                stdscr.addstr(y, 4, f"> {label}", curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addstr(y, 4, f"  {label}")

        # Hint-Zeile
        if allow_edit:
            hint = "[Enter] Auswählen  [Tab] Bearbeiten  [ESC] Abbrechen"
        else:
            hint = "[Enter] Auswählen  [ESC] Abbrechen"
        stdscr.addstr(height - 2, 2, hint, curses.color_pair(2))

        stdscr.refresh()

        key = stdscr.getch()

        if (
            key == curses.KEY_UP or key == ord("k") or key == curses.KEY_BTAB
        ):  # Shift+Tab
            current = (current - 1) % len(items)
        elif (
            key == curses.KEY_DOWN or key == ord("j") or (key == 9 and not allow_edit)
        ):  # Tab nur ohne Edit-Modus
            current = (current + 1) % len(items)
        elif allow_edit and key == 9:  # Tab im Edit-Modus → Editierdialog
            return (items[current][0], True)
        elif key == ord("\n"):
            if allow_edit:
                return (items[current][0], False)
            return items[current][0]
        elif key == 27 or key == ord("q"):
            if allow_edit:
                return (None, False)
            return None


def curses_browse(stdscr, title: str, summary: str, items: list):
    """Scrollbare Read-Only-Ansicht für Dateilisten"""
    curses.curs_set(0)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Guard-Clause für zu kleine Terminals
    if height < 8 or width < 40:
        stdscr.addstr(0, 0, "Terminal zu klein!")
        stdscr.getch()
        return

    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    current = 0
    # Verfügbare Zeilen für die Liste: Header(3) + Summary(1) + Leerzeile(1) oben, Hint(2) unten
    viewport_height = height - 7

    if not items:
        stdscr.addstr(2, 2, title, curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(4, 4, "Keine Dateien vorhanden.")
        stdscr.addstr(height - 2, 2, "ESC Zurück", curses.color_pair(2))
        stdscr.refresh()
        while True:
            key = stdscr.getch()
            if key == 27:
                return
        return

    while True:
        stdscr.clear()

        # Titel
        stdscr.addstr(1, 2, title, curses.color_pair(1) | curses.A_BOLD)

        # Summary
        stdscr.addstr(2, 2, summary, curses.color_pair(2))

        # Scroll-Offset berechnen
        scroll_offset = 0
        if current >= viewport_height:
            scroll_offset = current - viewport_height + 1

        # Dateiliste
        list_start_y = 4
        for i in range(viewport_height):
            idx = scroll_offset + i
            if idx >= len(items):
                break
            y = list_start_y + i
            if y >= height - 2:
                break

            _, label = items[idx]
            # Auf Terminalbreite beschneiden
            display = label[: width - 6]

            if idx == current:
                stdscr.addstr(
                    y, 4, f"> {display}", curses.color_pair(1) | curses.A_BOLD
                )
            else:
                stdscr.addstr(y, 4, f"  {display}")

        # Position-Indikator und Hint
        pos_text = f"[{current + 1}/{len(items)}]"
        hint = "↑↓/j/k Navigieren | ESC Zurück"
        stdscr.addstr(height - 2, 2, hint, curses.color_pair(2))
        stdscr.addstr(
            height - 2, width - len(pos_text) - 2, pos_text, curses.color_pair(2)
        )

        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP or key == ord("k") or key == curses.KEY_BTAB:
            current = (current - 1) % len(items)
        elif key == curses.KEY_DOWN or key == ord("j") or key == 9:  # Tab
            current = (current + 1) % len(items)
        elif key == 27:
            return


def curses_message(stdscr, title: str, message: str):
    """Zeigt eine Meldung und wartet auf Tastendruck"""
    curses.curs_set(0)
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    y = height // 2 - 3
    stdscr.addstr(
        y,
        max(0, (width - len(title)) // 2),
        title,
        curses.color_pair(1) | curses.A_BOLD,
    )
    lines = message.split("\n")
    for i, line in enumerate(lines):
        stdscr.addstr(
            y + 2 + i, max(0, (width - len(line)) // 2), line, curses.color_pair(2)
        )
    hint = "[ Beliebige Taste drücken ]"
    stdscr.addstr(y + 2 + len(lines) + 1, max(0, (width - len(hint)) // 2), hint)
    stdscr.refresh()
    stdscr.getch()


class ConfigManager:
    """Verwaltet config.yaml mit Export/Import-History"""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        self.config_path = Path(config_path)
        self.config = self.load_config()

    def load_config(self) -> Dict:
        """Lädt Config oder erstellt Default falls nicht vorhanden"""
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
        except Exception as e:
            # Bei korrupter Config: Backup erstellen und Default verwenden
            print(f"Config-Datei korrupt: {e}")
            backup_path = self.config_path.with_suffix(".yaml.bak")
            if self.config_path.exists():
                shutil.copy(self.config_path, backup_path)
            return default_config

    def save_config(self, config: Optional[Dict] = None) -> None:
        """Speichert Config in YAML"""
        if config is None:
            config = self.config

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(
                config, f, default_flow_style=False, allow_unicode=True, sort_keys=False
            )

    def add_to_history(self, path: Path, history_type: str) -> None:
        """Fügt Pfad zur History hinzu, limitiert auf max_history_entries"""
        if history_type not in ["export", "import"]:
            raise ValueError(f"Invalid history_type: {history_type}")

        history_key = "history"
        history = self.config[history_key]

        # Duplikate entfernen
        path_str = str(path.absolute())
        history = [h for h in history if h.get("path") != path_str]

        # Neuen Eintrag vorne einfügen
        history.insert(0, {"path": path_str, "timestamp": datetime.now().isoformat(), "type": history_type})

        # Auf max_entries limitieren
        max_entries = self.config["max_history_entries"]
        history = history[:max_entries]

        self.config[history_key] = history
        self.save_config()

    def get_history(self, history_type: str) -> List[Dict]:
        """Gibt History-Liste zurück"""
        if history_type not in ["export", "import"]:
            raise ValueError(f"Invalid history_type: {history_type}")

        history_key = "history"
        return self.config.get(history_key, [])

    def record_reset(self) -> None:
        """Speichert aktuellen Zeitstempel als letzten Reset-Zeitpunkt"""
        self.config["last_reset_timestamp"] = datetime.now().isoformat()
        self.save_config()

    def toggle_bool_option(self, key: str) -> bool:
        """Negiert Bool-Wert in Config und speichert zurück"""
        self.config[key] = not self.config.get(key, False)
        self.save_config()
        return self.config[key]


class ClaudeHomeManager:
    """Verwaltet ClaudeHome-Operationen (Reset, Export, Import)"""

    def __init__(
        self, claude_home_path: Path, config_manager: Optional["ConfigManager"] = None
    ):
        self.claude_home = Path(claude_home_path)
        self.settings_file = self.claude_home / "settings.local.json"
        self.config_manager = config_manager

    def is_empty(self) -> bool:
        """Prüft ob ClaudeHome leer ist (ignoriert settings.local.json)"""
        if not self.claude_home.exists():
            return True

        file_count = sum(
            1
            for item in self.claude_home.rglob("*")
            if item.is_file() and item != self.settings_file
        )
        return file_count == 0

    def get_status(self) -> Dict:
        """Gibt Status zurück: {is_empty, file_count, size_mb}"""
        is_empty = self.is_empty()

        if is_empty:
            return {"is_empty": True, "file_count": 0, "size_mb": 0.0}

        file_count = 0
        total_size = 0

        for item in self.claude_home.rglob("*"):
            if item.is_file() and item != self.settings_file:
                file_count += 1
                total_size += item.stat().st_size

        size_mb = total_size / (1024 * 1024)

        return {
            "is_empty": False,
            "file_count": file_count,
            "size_mb": round(size_mb, 2),
        }

    def get_contents(self) -> List[Tuple[str, str]]:
        """Gibt Dateiliste zurück: [(relative_path, display_label), ...]"""
        if not self.claude_home.exists():
            return []

        entries = []
        for item in sorted(self.claude_home.rglob("*")):
            if not item.is_file():
                continue

            rel_path = str(item.relative_to(self.claude_home))
            size = item.stat().st_size

            # Menschenlesbare Größe
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"

            label = f"{rel_path}  ({size_str})"

            # settings.local.json mit 🔒 markieren
            if item.name == "settings.local.json":
                label = f"🔒 {label}"

            entries.append((rel_path, label))

        return entries

    def reset(self) -> bool:
        """Löscht ClaudeHome, bewahrt settings.local.json"""
        try:

            # ClaudeHome-Inhalt leeren
            if self.claude_home.exists():
                for item in self.claude_home.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
            else:
                self.claude_home.mkdir(parents=True, exist_ok=True)

            print("✓ ClaudeHome erfolgreich zurückgesetzt")
            return True

        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except Exception as e:
            print(f"✗ Fehler beim Reset: {e}")
            return False

    def export_to(self, destination: Path) -> bool:
        """Exportiert ClaudeHome zu Ziel-Pfad"""
        try:
            destination = Path(destination)

            if not destination.parent.exists():
                curses.wrapper(
                    curses_message,
                    "Fehler",
                    f"Elternverzeichnis existiert nicht:\n{destination.parent}",
                )
                return False

            # Bestätigung wenn Ziel existiert (sofern nicht per Config deaktiviert)
            if destination.exists():
                dont_ask = (
                    self.config_manager.config.get(
                        "dont_ask_on_export_overwrite", False
                    )
                    if self.config_manager
                    else False
                )
                if not dont_ask:
                    merge = curses.wrapper(
                        curses_confirm,
                        f"Das Ziel ({destination}) existiert bereits.\n"
                        "Dateien hinzufügen / überschreiben?",
                        default=False,
                    )
                    if not merge:
                        return False

            # Ignore-Patterns aus Config laden
            ignore_patterns = []
            if self.config_manager:
                ignore_patterns = self.config_manager.config.get(
                    "export_ignore_patterns", []
                )

            # ClaudeHome kopieren mit ignore patterns
            if ignore_patterns:
                shutil.copytree(
                    self.claude_home,
                    destination,
                    ignore=shutil.ignore_patterns(*ignore_patterns),
                    dirs_exist_ok=True,
                )
            else:
                shutil.copytree(self.claude_home, destination, dirs_exist_ok=True)
            print(f"✓ Erfolgreich exportiert nach: {destination}")

            # Reset-Option nur wenn per Config aktiviert (default: Ja)
            ask_for_reset = (
                self.config_manager.config.get("ask_for_reset", True)
                if self.config_manager
                else True
            )
            if ask_for_reset:
                reset_now = curses.wrapper(
                    curses_confirm, "ClaudeHome jetzt zurücksetzen?", default=False
                )
                if reset_now:
                    return self.reset()

            return True

        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except Exception as e:
            print(f"✗ Fehler beim Export: {e}")
            return False

    def export_file_to(self, rel_file_path: str, destination: Path) -> bool:
        """Exportiert eine einzelne Datei aus ClaudeHome nach destination"""
        source_file = self.claude_home / rel_file_path

        if not source_file.exists():
            curses.wrapper(
                curses_message, "Fehler", f"Datei nicht gefunden:\n{source_file}"
            )
            return False

        # Blacklist-Check: Warnung wenn Datei einem Ignore-Pattern entspricht
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
        except Exception as e:
            curses.wrapper(curses_message, "Fehler", f"Fehler beim Export:\n{e}")
            return False

    def import_file_from(self, source_file: Path) -> bool:
        """Importiert eine einzelne Datei nach ClaudeHome-Root"""
        if not source_file.exists():
            curses.wrapper(
                curses_message, "Fehler", f"Quelldatei nicht gefunden:\n{source_file}"
            )
            return False

        # Blacklist-Check: Warnung wenn Datei einem Ignore-Pattern entspricht
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
        except Exception as e:
            curses.wrapper(curses_message, "Fehler", f"Fehler beim Import:\n{e}")
            return False

    def import_from(self, source: Path) -> bool:
        """Importiert ClaudeHome von Quell-Pfad, bewahrt settings.local.json"""
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

            # Bestätigung wenn ClaudeHome nicht leer
            if not self.is_empty():
                print("ClaudeHome enthält Daten. Aktuelle Daten werden gelöscht!")
                confirm = curses.wrapper(
                    curses_confirm,
                    "Alle Daten im ClaudeHome werden beim Import gelöscht!\n"
                    "Fortfahren?",
                    default=False,
                )
                if not confirm:
                    print("Import abgebrochen")
                    return False

            # ClaudeHome-Inhalt leeren
            if self.claude_home.exists():
                for item in self.claude_home.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
            else:
                self.claude_home.mkdir(parents=True, exist_ok=True)

            # Ignore-Patterns aus Config laden
            ignore_patterns = []
            if self.config_manager:
                ignore_patterns = self.config_manager.config.get(
                    "import_ignore_patterns", []
                )

            # Von Quelle kopieren mit ignore patterns
            if ignore_patterns:
                shutil.copytree(
                    source,
                    self.claude_home,
                    ignore=shutil.ignore_patterns(*ignore_patterns),
                    dirs_exist_ok=True,
                )
            else:
                shutil.copytree(source, self.claude_home, dirs_exist_ok=True)

            print(f"✓ Erfolgreich importiert von: {source}")
            return True

        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return False
        except Exception as e:
            print(f"✗ Fehler beim Import: {e}")
            return False


class LauncherApp:
    """Haupt-Controller für den Launcher"""

    def __init__(
        self,
        claude_home: Path,
        config_manager: ConfigManager,
        claude_binary: Path,
        export_path: Optional[Path] = None,
        import_path: Optional[Path] = None,
    ):
        self.config_manager = config_manager
        self.claude_home_manager = ClaudeHomeManager(claude_home, config_manager)
        self.claude_binary = Path(claude_binary)
        self.export_path = export_path
        self.import_path = import_path

        # ClaudeHome erstellen falls nicht vorhanden wird in main() behandelt

    def get_menu_items(self) -> List[Tuple[str, str]]:
        """Generiert Menü-Items basierend auf ClaudeHome-Status"""
        is_empty = self.claude_home_manager.is_empty()

        items = []

        # Plan immer verfügbar
        items.append(("plan", "📝 Plan schreiben"))

        # Export und Browse nur wenn Daten vorhanden
        if not is_empty:
            items.append(("export", "⤴️  Exportieren"))
            items.append(("browse", "📂 Inhalt von ClaudeHome anzeigen"))

        # Import immer verfügbar
        items.append(("import", "⤵️  Importieren"))

        # Session Start/Resume
        if is_empty:
            items.append(("start", "▶️  Neue Sitzung starten"))
        else:
            items.append(("resume", "▶️  Sitzung fortsetzen"))

        # Shell immer verfügbar
        items.append(("shell", "🖥️  Shell öffnen"))

        # Reset nur wenn Daten vorhanden
        if not is_empty:
            items.append(("reset", "🔄 Reset"))

        return items

    def select_path_with_history(self, history_type: str) -> Optional[Path]:
        """Pfad-Auswahl mit History oder manuelle Eingabe.

        Enter = Pfad direkt übernehmen, e = Editierdialog öffnen.
        """
        # Kontextspezifische Labels für Export und Import
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
            # History-Items für Auswahl vorbereiten
            history_items = []
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
                history_items.append((path, f"{icon} {path} ({timestamp})"))

            # "Neuen Pfad eingeben" Option
            history_items.append(("__custom__", "📝 Neuen Pfad eingeben"))

            select_result = curses.wrapper(
                curses_select,
                select_title,
                history_items,
                0,
                True,  # allow_edit=True: Tab-Taste öffnet Editierdialog
            )
            selected, edit_mode = select_result or (None, False)

            if selected is None:
                return None

            if selected == "__custom__":
                # Eigene Eingabe: immer Input-Dialog (leer)
                path_input = curses.wrapper(curses_input, input_prompt, "")
            elif edit_mode:
                # e-Taste: Edit-Dialog mit vorausgefülltem Wert
                path_input = curses.wrapper(curses_input, input_edit_prompt, selected)
            else:
                # Enter: Pfad direkt übernehmen ohne Edit-Dialog
                path_input = selected
        else:
            # Keine History: Direkte Eingabe
            path_input = curses.wrapper(curses_input, input_prompt, "")

        if path_input is None or path_input.strip() == "":
            return None

        return Path(path_input).expanduser()

    def handle_reset(self) -> None:
        """Reset-Operation"""
        if self.claude_home_manager.is_empty():
            print("ClaudeHome ist bereits leer")
            return

        print("Alle Daten im ClaudeHome werden gelöscht!")
        print("(settings.local.json bleibt erhalten)")
        confirm = curses.wrapper(
            curses_confirm,
            "Alle Daten im ClaudeHome werden gelöscht!" "\nFortfahren?",
            default=False,
        )

        if confirm:
            if self.claude_home_manager.reset():
                self.config_manager.record_reset()

    def handle_export(self) -> None:
        """Export-Operation mit Auto-Detect: Single File oder Folder"""
        if self.claude_home_manager.is_empty():
            curses.wrapper(
                curses_message, "Export", "ClaudeHome ist leer, nichts zu exportieren"
            )
            return

        # Pfad aus CLI-Argument oder interaktiv wählen
        if self.export_path:
            destination = self.export_path
        else:
            destination = self.select_path_with_history("export")
            if destination is None:
                return

        # Auto-Detect: Dateiendung oder existierende Datei → Single File Mode
        if destination.suffix != "" or destination.is_file():
            self._handle_single_file_export(destination)
        else:
            # Folder Mode: bestehender Export-Flow
            success = self.claude_home_manager.export_to(destination)
            if success:
                self.config_manager.add_to_history(destination, "export")

    def _handle_single_file_export(self, destination: Path) -> None:
        """Exportiert eine einzelne Datei aus ClaudeHome – Dateiname aus Zielpfad"""
        filename = destination.name

        # Datei anhand des Namens in ClaudeHome suchen
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

        # Erste Übereinstimmung verwenden (gleiche Dateinamen in Unterordnern sind selten)
        source_file = matches[0]
        rel_path = str(source_file.relative_to(self.claude_home_manager.claude_home))

        # Bestätigung wenn Zieldatei existiert (sofern nicht per Config deaktiviert)
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
        """Import-Operation mit Auto-Detect: Single File oder Folder"""
        # Pfad aus CLI-Argument oder interaktiv wählen
        if self.import_path:
            source = self.import_path
        else:
            source = self.select_path_with_history("import")
            if source is None:
                return

        if source.is_file():
            # Single File Mode: Datei direkt nach ClaudeHome-Root kopieren
            success = self.claude_home_manager.import_file_from(source)
            if success:
                self.config_manager.add_to_history(source, "import")
        elif source.is_dir():
            # Folder Mode: bestehender Import-Flow
            success = self.claude_home_manager.import_from(source)
            if success:
                self.config_manager.add_to_history(source, "import")
        else:
            curses.wrapper(curses_message, "Fehler", f"Pfad existiert nicht:\n{source}")

    def launch_claude(self, resume: bool) -> bool:
        """Startet Claude als Subprocess, kehrt zum Menü zurück nach Exit"""
        if not self.claude_binary.exists():
            print(f"✗ Claude Binary nicht gefunden: {self.claude_binary}")
            print("Bitte installiere Claude Code oder gib den korrekten Pfad an")
            return True

        action = "Resume Session" if resume else "Starte neue Session"
        print(f"{action}...")

        try:
            # Bildschirm vor Claude Start leeren
            subprocess.run(["/usr/bin/clear"], check=False)

            # macOS Theme synchronisieren
            self._apply_macos_theme()

            env = os.environ.copy()
            claude_env = self.config_manager.config.get("claude_env", {})
            env.update(claude_env)

            result = subprocess.run(
                [str(self.claude_binary)],
                cwd=str(self.claude_home_manager.claude_home),
                env=env,
            )
            print(f"\nClaude wurde beendet (Exit Code: {result.returncode})")
            return True
        except Exception as e:
            print(f"✗ Fehler beim Starten von Claude: {e}")
            return True

    def _apply_macos_theme(self) -> None:
        """Setzt Claude-Theme basierend auf macOS Dark/Light Mode"""
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
        )
        # Kein Output = Light Mode (macOS Standard wenn kein Dark Mode)
        theme = "dark" if result.stdout.strip() == "Dark" else "light"
        claude_json_path = Path.home() / ".claude.json"
        settings = {}
        if claude_json_path.exists():
            try:
                with open(claude_json_path, "r") as f:
                    settings = json.load(f)
            except Exception:
                settings = {}
        settings["theme"] = theme
        with open(claude_json_path, "w") as f:
            json.dump(settings, f, indent=2)

    def handle_browse(self) -> None:
        """Zeigt ClaudeHome-Inhalt in scrollbarer Ansicht"""
        contents = self.claude_home_manager.get_contents()
        status = self.claude_home_manager.get_status()
        summary = f"{status['file_count']} Dateien | {status['size_mb']} MB"
        curses.wrapper(curses_browse, "📂 ClaudeHome Inhalt", summary, contents)

    def handle_plan(self) -> None:
        """Öffnet oder erstellt Plan.md im ClaudeHome mit vi"""
        plan_file = self.claude_home_manager.claude_home / "Plan.md"
        subprocess.run(["vi", str(plan_file)])

    def handle_shell(self) -> None:
        """Öffnet eine Shell im ClaudeHome-Verzeichnis"""
        shell = os.environ.get("SHELL", "/bin/zsh")
        subprocess.run([shell], cwd=str(self.claude_home_manager.claude_home))

    def handle_action(self, action: str) -> Tuple[bool, bool]:
        """Führt Aktion aus, return (continue_loop, wait_for_enter)"""
        if action == "reset":
            self.handle_reset()
            return (True, False)
        elif action == "start" or action == "resume":
            should_continue = self.launch_claude(action == "resume")
            return (should_continue, False)
        elif action == "export":
            self.handle_export()
            return (True, False)
        elif action == "import":
            self.handle_import()
            return (True, False)
        elif action == "browse":
            self.handle_browse()
            return (True, False)
        elif action == "plan":
            self.handle_plan()
            return (True, False)
        elif action == "shell":
            self.handle_shell()
            return (True, False)
        elif action == "quit":
            print("Auf Wiedersehen!")
            return (False, False)

        return (True, True)

    def run(self) -> None:
        """Hauptschleife"""
        try:
            # Direkt-Modus: Export
            if self.export_path:
                self.handle_export()
                return

            # Direkt-Modus: Import
            if self.import_path:
                self.handle_import()
                return

            # Interaktiver Modus
            while True:
                menu_items = self.get_menu_items()

                # Status-Text generieren
                status = self.claude_home_manager.get_status()
                claude_home_path = str(self.claude_home_manager.claude_home)

                # Config-Optionen für Footer auslesen
                ask_reset = self.config_manager.config.get("ask_for_reset", True)
                dont_ask_overwrite = self.config_manager.config.get(
                    "dont_ask_on_export_overwrite", False
                )
                ask_reset_str = "Ja" if ask_reset else "Nein"
                # dont_ask_on_export_overwrite=True bedeutet NICHT fragen → Überschreiben bestätigen: Nein
                overwrite_ask_str = "Nein" if dont_ask_overwrite else "Ja"
                footer_hints = (
                    f"  [r] Refresh  [x] Nach Export zurücksetzen: {ask_reset_str}"
                    f"  [o] Überschreiben bestätigen: {overwrite_ask_str}  [q] Beenden"
                )

                # Letzten Export aus History ermitteln (nur wenn neuer als letzter Reset)
                all_history = self.config_manager.config.get("history", [])
                last_export = next((h for h in all_history if h.get("type") == "export"), None)
                last_reset_ts = self.config_manager.config.get("last_reset_timestamp")

                if last_export:
                    export_ts = datetime.fromisoformat(last_export["timestamp"])
                    reset_ts = datetime.fromisoformat(last_reset_ts) if last_reset_ts else None
                    if reset_ts is None or export_ts > reset_ts:
                        export_line = f"   Letzter Export: {export_ts.strftime('%d.%m.%Y %H:%M')}\n"
                    else:
                        export_line = ""
                else:
                    export_line = ""

                if status["is_empty"]:
                    status_text = (
                        f"📁 {claude_home_path}\n"
                        f"   (leer)\n"
                        + export_line
                        + footer_hints
                    )
                else:
                    status_text = (
                        f"📁 {claude_home_path}\n"
                        f"   {status['file_count']} Dateien · {status['size_mb']} MB\n"
                        + export_line
                        + footer_hints
                    )

                # Curses Menü anzeigen
                try:
                    result = curses.wrapper(
                        curses_menu, "Claude Code Launcher", status_text, menu_items, 0
                    )

                    if result is None:
                        print("Auf Wiedersehen!")
                        break
                except KeyboardInterrupt:
                    print("\nAuf Wiedersehen!")
                    break
                except Exception as e:
                    print(f"✗ Interaktives Menü nicht verfügbar: {e}")
                    print(
                        "Bitte verwende --export oder --import für nicht-interaktive Nutzung"
                    )
                    break

                # Refresh: Config neu laden und Loop-Neustart berechnet Status neu
                if result == "__refresh__":
                    self.config_manager.config = self.config_manager.load_config()
                    continue
                elif result == "__toggle_ask_reset__":
                    self.config_manager.toggle_bool_option("ask_for_reset")
                    continue
                elif result == "__toggle_overwrite_ask__":
                    self.config_manager.toggle_bool_option(
                        "dont_ask_on_export_overwrite"
                    )
                    continue

                # Aktion ausführen
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


def main():
    """Haupteinstiegspunkt"""
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
        "--config", default=None, help="Pfad zur Config-Datei (default: ./config.yaml)"
    )
    parser.add_argument(
        "--claude-binary",
        default=None,
        help="Pfad zum Claude Binary (default: automatische Erkennung via PATH)",
    )

    args = parser.parse_args()

    # Claude Binary Pfad ermitteln
    if args.claude_binary:
        claude_binary = Path(args.claude_binary)
    else:
        # Automatische Erkennung via PATH
        claude_path = shutil.which("claude")
        if claude_path:
            claude_binary = Path(claude_path)
        else:
            print("✗ Claude Binary nicht gefunden im PATH")
            print(
                "Bitte installiere Claude Code oder gib den Pfad mit --claude-binary an"
            )
            sys.exit(1)

    # Manager initialisieren
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

    # Pfade vorbereiten
    export_path = Path(args.export_path).absolute() if args.export_path else None
    import_path = Path(args.import_path).absolute() if args.import_path else None

    # Launcher starten
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
