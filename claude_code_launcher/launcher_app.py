"""Haupt-Controller: hält ConfigManager + WorkspaceManager, orchestriert alle curses-Dialoge."""

import curses
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .config_manager import ConfigManager
from .constants import (
    ACTION_TO_SHORTCUT,
    CLEAR_BINARY,
    DEFAULT_SHELL,
    DEFAULTS_BINARY,
    SHORTCUT_LABELS,
    VSCODE_BINARY,
)
from .remote_target import _is_remote_target, _remote_path_part
from .ui_curses import (
    curses_browse,
    curses_confirm,
    curses_input,
    curses_menu,
    curses_message,
    curses_select,
)
from .usage_stats import (
    USAGE_CACHE_REQUIRED_KEYS,
    _fetch_claude_usage_stats,
    _format_absolute_time,
    _format_relative_reset,
    _usage_stats_from_cache,
    _usage_stats_to_cache,
)
from .workspace_manager import WorkspaceManager


class LauncherApp:
    """Haupt-Controller für den Launcher."""

    def __init__(
        self,
        workspace: Path,
        config_manager: ConfigManager,
        claude_binary: Path,
        version: str,
        export_path: Path | str | None = None,
        import_path: Path | str | None = None,
    ):
        self.config_manager = config_manager
        self.workspace_manager = WorkspaceManager(workspace, config_manager)
        self.claude_binary = Path(claude_binary)
        self.version = version
        self.export_path = export_path
        self.import_path = import_path

    def _get_cached_usage_stats(self, force: bool = False) -> dict[str, Any] | None:
        """Liefert Claude-Nutzungsdaten aus config.toml, ruft openusage nur bei abgelaufenem Cache neu ab.

        Schlägt ein nötiger Neu-Abruf fehl (openusage fehlt/Timeout/Fehler), wird als
        Fallback der letzte bekannte Cache-Wert zurückgegeben statt die Anzeige
        auszublenden. `force=True` (manueller Refresh via `r`) überspringt die
        `expires_at`-Prüfung und fragt openusage immer neu ab.
        """
        self.config_manager.reload()
        cache = self.config_manager.config.get("usage_cache", {})
        has_cache = USAGE_CACHE_REQUIRED_KEYS.issubset(cache)

        if not force and has_cache:
            expires_at = datetime.fromisoformat(
                cache["expires_at"].replace("Z", "+00:00")
            )
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
        """Generiert Menü-Items (action_key, label) basierend auf Workspace-Status."""
        is_empty = self.workspace_manager.is_empty()
        items: list[tuple[str, str]] = []

        items.append(("plan", "📝 Prompts verwalten"))
        items.append(("start", "🚀 Sitzung starten"))

        if not is_empty:
            items.append(("export", "🔼 Exportieren"))

        items.append(("import", "🔽 Importieren"))
        items.append(("open_import_source", "🧭 Importquelle in VS Code öffnen"))

        if not is_empty:
            items.append(("browse", "📂 Inhalt von Workspace anzeigen"))

        items.append(("shell", "💻 Shell öffnen"))

        if not is_empty:
            items.append(("reset", "🔄 Reset"))

        return items

    def _build_status_text(self, status: dict) -> str:
        """Mehrzeiliger Status-String fürs Hauptmenü: Info-Zeilen + Footer als letzte Zeile."""
        workspace_path = str(self.workspace_manager.workspace)

        recent_shortcuts = self.config_manager.config.get("recent_shortcuts", [])
        footer_segments = ["[h] Hilfe"]
        footer_segments += [
            f"[{key}] {SHORTCUT_LABELS[key]}"
            for key in recent_shortcuts
            if key in SHORTCUT_LABELS
        ]
        footer_segments.append("[q] Beenden")
        footer = "  " + "  ".join(footer_segments)

        all_history = self.config_manager.config.get("history", [])
        last_export = next(
            (h for h in all_history if h.get("type") == "export" and not h.get("synthetic")),
            None,
        )
        last_import = next((h for h in all_history if h.get("type") == "import"), None)
        last_reset_ts = self.config_manager.config.get("last_reset_timestamp")
        export_line = self._get_export_line(last_export, last_reset_ts)
        import_line = self._get_import_line(last_import)

        content_line = (
            "   (leer)"
            if status["is_empty"]
            else f"   {status['file_count']} Dateien · {status['size_mb']} MB"
        )

        return (
            f"📁 {workspace_path}\n{content_line}\n{export_line}{import_line}{footer}"
        )

    @staticmethod
    def _get_export_line(last_export: dict | None, last_reset_ts: str | None) -> str:
        """Export-Info-Zeile, nur wenn der Export neuer als der letzte Reset ist."""
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
        """Import-Info-Zeile, kein Reset-Bezug (Reset betrifft nur Export)."""
        if not last_import:
            return ""
        import_ts = datetime.fromisoformat(last_import["timestamp"])
        folder_name = Path(last_import["path"]).name
        return f"   Letzter Import: {import_ts.strftime('%d.%m.%Y %H:%M')} ({folder_name})\n"

    @staticmethod
    def _build_usage_stats_text(usage: dict[str, Any] | None) -> str | None:
        """Vierzeiliger Text für die Claude-Nutzungsstatistik-Spalte, oder None ohne Daten."""
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
        """Verarbeitet Sentinel-Rückgaben aus dem Menü (Refresh, Toggle-Hotkeys)."""
        if result == "__refresh__":
            self.config_manager.reload()
            self.config_manager.record_shortcut_usage("r")
            return True
        if result == "__toggle_ask_reset__":
            self.config_manager.toggle_bool_option("ask_for_reset")
            return True
        if result == "__toggle_overwrite_ask__":
            self.config_manager.toggle_bool_option("dont_ask_on_export_overwrite")
            return True
        return False

    def select_path_with_history(self, history_type: str) -> Path | str | None:
        """Pfad-Auswahl mit History oder manuelle Eingabe. Enter = übernehmen, Tab = bearbeiten."""
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
            # Nicht `raw or (None, False)` - das schlägt bei raw=(None, False) fehl
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

        if _is_remote_target(path_input):
            return path_input

        return Path(path_input).expanduser()

    @staticmethod
    def _build_history_items(history: list[dict]) -> list[tuple[str, str]]:
        """Bereitet History-Einträge für curses_select vor (Icon + Timestamp im Label)."""
        items = []
        for entry in history:
            path = entry["path"]
            timestamp = datetime.fromisoformat(entry["timestamp"]).strftime(
                "%Y-%m-%d %H:%M"
            )
            if _is_remote_target(path):
                icon = "🌐"
            else:
                path_obj = Path(path)
                if path_obj.is_file():
                    icon = "📄"
                elif path_obj.is_dir():
                    icon = "📁"
                else:
                    icon = "❓"  # Pfad existiert nicht mehr
            items.append((path, f"{icon} {path} ({timestamp})"))
        return items

    def _get_first_history_path(self, history_type: str) -> Path | str | None:
        """Pfad des neuesten History-Eintrags dieses Typs, oder None (Alt-Einträge ohne
        type-Feld zählen für beide Typen)."""
        self.config_manager.reload()
        history = self.config_manager.config.get("history", [])
        entry = next(
            (h for h in history if h.get("type", history_type) == history_type), None
        )
        if entry is None:
            return None
        path_str = entry["path"]
        if _is_remote_target(path_str):
            return path_str
        return Path(path_str).expanduser()

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
        if isinstance(source, str):
            curses.wrapper(
                curses_message, "VS Code", "VS Code kann keine Remote-Pfade (SSH) öffnen"
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

    def _confirm_export_target(self, destination: Path | str) -> bool:
        """Warnt wenn destination vom letzten Import-Pfad abweicht (Folder-Export hat
        Mirror-Semantik, überträgt also auch Löschungen). True = fortfahren."""
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

    @staticmethod
    def _remote_target_is_single_file(path_str: str) -> bool:
        """Dateiendungs-Heuristik für SSH-Remote-Ziele (is_file()/is_dir() sind ohne
        SSH-Verbindung nicht prüfbar), analog zur lokalen Export-Heuristik."""
        return PurePosixPath(_remote_path_part(path_str)).suffix != ""

    def handle_export(self, destination: Path | str | None = None) -> None:
        """Export-Operation mit Auto-Detect: Single File oder Folder."""
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
        if isinstance(destination, str):
            is_single_file = self._remote_target_is_single_file(destination)
        else:
            is_single_file = destination.suffix != "" or destination.is_file()

        if is_single_file:
            self._handle_single_file_export(destination)
        else:
            self._handle_folder_export(destination)

    def _handle_folder_export(self, destination: Path | str) -> None:
        """Folder-Export: Vorab-Checks/Dialoge hier, eigentlicher Sync in WorkspaceManager.

        Bei einem Remote-Ziel (str) entfallen die Vorab-Checks – ohne SSH-Verbindung
        nicht prüfbar, rsync übernimmt Merge/Overwrite selbst.
        """
        if isinstance(destination, Path):
            if not destination.parent.exists():
                curses.wrapper(
                    curses_message,
                    "Fehler",
                    f"Elternverzeichnis existiert nicht:\n{destination.parent}",
                )
                return

            if destination.exists() and self.workspace_manager.needs_overwrite_confirmation():
                confirmed = curses.wrapper(
                    curses_confirm,
                    f"Das Ziel ({destination}) existiert bereits.\n"
                    "Ziel wird synchronisiert – überzählige Dateien im Ziel werden gelöscht!\n"
                    "Fortfahren?",
                    default=False,
                    mouse_enabled=self._is_mouse_navigation_enabled(),
                )
                if not confirmed:
                    return

        result = self.workspace_manager.export_to(destination)
        if not result.success:
            return  # Fehlertext wurde bereits per print() in WorkspaceManager ausgegeben

        self.config_manager.add_to_history(destination, "export")

        ask_for_reset = self.config_manager.config.get("ask_for_reset", True)
        if ask_for_reset:
            reset_confirmed = curses.wrapper(
                curses_confirm,
                "Workspace jetzt zurücksetzen?",
                default=False,
                mouse_enabled=self._is_mouse_navigation_enabled(),
            )
            if reset_confirmed:
                self.workspace_manager.reset()

    def _handle_single_file_export(self, destination: Path | str) -> None:
        """Exportiert eine einzelne Datei aus Workspace – Dateiname aus Zielpfad."""
        filename = (
            destination.name
            if isinstance(destination, Path)
            else PurePosixPath(_remote_path_part(destination)).name
        )
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

        # Reihenfolge von rglob() ist nicht garantiert – bei mehreren Treffern
        # den User informieren statt still die erste Fundstelle zu exportieren.
        if len(matches) > 1:
            curses.wrapper(
                curses_message,
                "Export",
                f"Mehrere Dateien namens '{filename}' gefunden.\n"
                f"Verwende: {rel_path}",
            )

        if (
            isinstance(destination, Path)
            and destination.exists()
            and self.workspace_manager.needs_overwrite_confirmation()
        ):
            overwrite = curses.wrapper(
                curses_confirm,
                f"Die Zieldatei ({destination}) existiert bereits.\nÜberschreiben?",
                default=False,
                mouse_enabled=self._is_mouse_navigation_enabled(),
            )
            if not overwrite:
                return

        matched_pattern = self.workspace_manager.matched_ignore_pattern(
            source_file.name, "export_ignore_patterns"
        )
        if matched_pattern:
            curses.wrapper(
                curses_message,
                "Warnung",
                f"Datei entspricht Ignore-Pattern '{matched_pattern}'.\nExport wird trotzdem durchgeführt.",
            )

        result = self.workspace_manager.export_file_to(rel_path, destination)
        if not result.success:
            curses.wrapper(curses_message, "Fehler", result.error)
            return

        self.config_manager.add_to_history(destination, "export")

    def handle_import(self, source: Path | str | None = None) -> None:
        """Import-Operation mit Auto-Detect: Single File oder Folder.

        Bei einem Remote-Ziel (str) sind is_file()/is_dir() ohne SSH-Verbindung
        nicht prüfbar – Modus-Entscheidung dann über dieselbe Dateiendungs-Heuristik
        wie beim Export.
        """
        self.config_manager.reload()
        source = source or self.import_path or self.select_path_with_history("import")
        if source is None:
            return

        if isinstance(source, str):
            if self._remote_target_is_single_file(source):
                self._handle_single_file_import(source)
            else:
                self._handle_folder_import(source)
        elif source.is_file():
            self._handle_single_file_import(source)
        elif source.is_dir():
            self._handle_folder_import(source)
        else:
            curses.wrapper(curses_message, "Fehler", f"Pfad existiert nicht:\n{source}")

    def _handle_single_file_import(self, source: Path | str) -> None:
        """Single-File-Import: Ignore-Pattern-Warnung hier, eigentliche Kopie in WorkspaceManager."""
        filename = (
            source.name if isinstance(source, Path) else PurePosixPath(_remote_path_part(source)).name
        )
        matched_pattern = self.workspace_manager.matched_ignore_pattern(
            filename, "import_ignore_patterns"
        )
        if matched_pattern:
            curses.wrapper(
                curses_message,
                "Warnung",
                f"Datei entspricht Ignore-Pattern '{matched_pattern}'.\nImport wird trotzdem durchgeführt.",
            )

        result = self.workspace_manager.import_file_from(source)
        if not result.success:
            curses.wrapper(curses_message, "Fehler", result.error)
            return

        self.config_manager.add_to_history(source, "import")
        self.config_manager.add_to_history(source, "export", synthetic=True)

    def _handle_folder_import(self, source: Path | str) -> None:
        """Folder-Import: Lösch-Bestätigung hier, eigentlicher Sync in WorkspaceManager."""
        if not self.workspace_manager.is_empty():
            confirmed = curses.wrapper(
                curses_confirm,
                "Alle Daten im Workspace werden beim Import gelöscht!\nFortfahren?",
                default=False,
                mouse_enabled=self._is_mouse_navigation_enabled(),
            )
            if not confirmed:
                return

        result = self.workspace_manager.import_from(source)
        if not result.success:
            return  # Fehlertext wurde bereits per print() in WorkspaceManager ausgegeben

        self.config_manager.add_to_history(source, "import")
        self.config_manager.add_to_history(source, "export", synthetic=True)

    def launch_claude(self) -> bool:
        """Startet Claude als Subprocess, kehrt nach Exit zum Menü zurück (Rückgabe stets True)."""
        if not self.claude_binary.exists():
            print(f"✗ Claude Binary nicht gefunden: {self.claude_binary}")
            return True

        try:
            subprocess.run([CLEAR_BINARY], check=False)
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
        """Setzt Claude-Theme (~/.claude.json) basierend auf macOS Dark/Light Mode."""
        if sys.platform != "darwin":
            return
        result = subprocess.run(
            [DEFAULTS_BINARY, "read", "-g", "AppleInterfaceStyle"],
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

    def handle_prompt_sessions(self) -> None:
        """Öffnet den konfigurierten Prompt-Manager im Workspace-Verzeichnis."""
        binary = self.config_manager.config.get("prompt_manager_binary", "qDrover")
        args = self.config_manager.config.get("prompt_manager_args", [])
        try:
            subprocess.run([binary, *args], cwd=str(self.workspace_manager.workspace))
        except FileNotFoundError:
            curses.wrapper(
                curses_message,
                "Prompt-Manager",
                f"„{binary}“-Kommando nicht gefunden – prompt_manager_binary in config.toml prüfen",
            )

    def handle_shell(self) -> None:
        """Öffnet eine Login-Shell im Workspace-Verzeichnis."""
        shell = os.environ.get("SHELL", DEFAULT_SHELL)
        subprocess.run([shell, "-l"], cwd=str(self.workspace_manager.workspace))

    def handle_action(self, action: str) -> tuple[bool, bool]:
        """Führt Menü-Aktion aus, gibt (continue_loop, wait_for_enter) zurück."""
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
            self.handle_prompt_sessions()
        elif action == "shell":
            self.handle_shell()

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

            force_usage_refresh = False
            while True:
                status = self.workspace_manager.get_status()
                menu_items = self.get_menu_items()
                status_text = self._build_status_text(status)
                usage_stats_text = self._build_usage_stats_text(
                    self._get_cached_usage_stats(force=force_usage_refresh)
                )
                force_usage_refresh = False
                mouse_enabled = self._is_mouse_navigation_enabled()

                try:
                    result = curses.wrapper(
                        curses_menu,
                        "Claude Code Launcher",
                        self.version,
                        status_text,
                        menu_items,
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
                    if result == "__refresh__":
                        force_usage_refresh = True
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
