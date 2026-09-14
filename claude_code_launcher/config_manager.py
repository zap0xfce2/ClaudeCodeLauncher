"""Verwaltet config.toml mit Export/Import-History."""

import shutil
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import RECENT_SHORTCUTS_MAX_ENTRIES
from .toml_io import _dump_toml


class ConfigManager:
    """Verwaltet config.toml mit Export/Import-History."""

    def __init__(self, config_path: Path | None = None):
        """Lädt config.toml; ohne config_path Fallback auf eine Datei neben diesem Modul.

        main.py übergibt config_path stets explizit relativ zum Entry-Point, damit die
        Config beim kompilierten Binary im richtigen Verzeichnis landet statt im
        Paket-Ordner (dieser Fallback ist nur für Standalone-Nutzung/Tests gedacht).
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.toml"
        self.config_path = Path(config_path)
        self.config = self.load_config()

    def load_config(self) -> dict[str, Any]:
        """Lädt Config oder erstellt Default falls nicht vorhanden."""
        default_config = {
            "history": [],
            "max_history_entries": 10,
            "ignore_patterns": [],
            "export_ignore_patterns": [],
            "import_ignore_patterns": [],
            "claude_env": {},
            "claude_instruction": "",
            "ask_for_reset": True,
            "dont_ask_on_export_overwrite": False,
            "respect_gitignore": False,
            "mouse_navigation_enabled": True,
            "recent_shortcuts": [],
            "usage_cache": {},
            "prompt_manager_binary": "qDrover",
            "prompt_manager_args": [],
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
        """Speichert config (Standard: self.config) in TOML."""
        if config is None:
            config = self.config

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            f.write(_dump_toml(config))

    def add_to_history(
        self, path: Path | str, history_type: str, synthetic: bool = False
    ) -> None:
        """Fügt path zur History hinzu, limitiert auf max_history_entries.

        path als str bedeutet ein SSH-Remote-Ziel (z. B. "user@host:/pfad") und wird
        unverändert gespeichert statt via .absolute() als lokaler Pfad behandelt.

        synthetic=True markiert automatisch (nicht vom Nutzer ausgelöst) angelegte
        Einträge, z. B. den Export-Eintrag, den ein Import zum selben Pfad anlegt,
        damit Quick-Export (`e`) danach sofort funktioniert – wird von der
        "Letzter Export"-Statuszeile ignoriert (siehe LauncherApp._build_status_text()).
        """
        if history_type not in ["export", "import"]:
            raise ValueError(f"Invalid history_type: {history_type}")

        self.reload()
        history = self.config["history"]
        path_str = str(path) if isinstance(path, str) else str(path.absolute())

        # Duplikate pro (Pfad, Typ) entfernen, dann neuen Eintrag vorne einfügen;
        # Alt-Einträge ohne type-Feld gelten als Treffer und werden ersetzt
        history = [
            h
            for h in history
            if h.get("path") != path_str or h.get("type", history_type) != history_type
        ]
        entry: dict[str, Any] = {
            "path": path_str,
            "timestamp": datetime.now().isoformat(),
            "type": history_type,
        }
        if synthetic:
            entry["synthetic"] = True
        history.insert(0, entry)

        self.config["history"] = history[: self.config["max_history_entries"]]
        self.save_config()

    def get_history(self, history_type: str) -> list[dict]:
        """History-Einträge dieses Typs (Alt-Einträge ohne type-Feld zählen für beide Typen)."""
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
        """Negiert Bool-Wert in Config, speichert zurück und gibt den neuen Wert zurück."""
        self.reload()
        self.config[key] = not self.config.get(key, False)
        self.save_config()
        return self.config[key]

    def record_shortcut_usage(self, shortcut: str) -> None:
        """Merkt sich shortcut als zuletzt verwendet (neuestes zuerst, dedupliziert)."""
        self.reload()
        recent = [s for s in self.config.get("recent_shortcuts", []) if s != shortcut]
        recent.insert(0, shortcut)
        self.config["recent_shortcuts"] = recent[:RECENT_SHORTCUTS_MAX_ENTRIES]
        self.save_config()
