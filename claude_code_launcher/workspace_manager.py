"""Verwaltet Workspace-Operationen (Reset, Export, Import) – vollständig UI-frei.

Bestätigungs-/Fehlerdialoge liegen bewusst nicht hier, sondern in LauncherApp
(launcher_app.py), das diese Klasse orchestriert – dadurch bleibt WorkspaceManager
ohne curses testbar.
"""

import fnmatch
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .constants import (
    BYTES_PER_KB,
    BYTES_PER_MB,
    RSYNC_BASE_ARGS,
    RSYNC_BINARY,
    RSYNC_DELETE_EXCLUDED_ARG,
    RSYNC_FILE_COPY_ARGS,
)
from .remote_target import _remote_path_part

if TYPE_CHECKING:
    from .config_manager import ConfigManager


@dataclass
class OperationResult:
    """Ergebnis einer Export-/Import-Operation; error trägt den Fehlertext für Dialoge/Logs."""

    success: bool
    error: str | None = None


class WorkspaceManager:
    """Verwaltet Workspace-Operationen (Reset, Export, Import)."""

    def __init__(
        self,
        workspace_path: Path,
        config_manager: "ConfigManager | None" = None,
    ):
        self.workspace = Path(workspace_path)
        self.settings_file = self.workspace / "settings.local.json"
        self.config_manager = config_manager

    def is_empty(self) -> bool:
        """True wenn keine relevanten Dateien vorhanden sind (ignoriert settings.local.json/ignore_patterns)."""
        if not self.workspace.exists():
            return True
        patterns = self._get_ignore_patterns()
        return not any(
            item.is_file()
            and item != self.settings_file
            and self._is_file_ignored(item.name, patterns) is None
            for item in self.workspace.rglob("*")
        )

    def get_status(self) -> dict:
        """Liefert {is_empty, file_count, size_mb} nach denselben Ignore-Regeln wie is_empty()."""
        patterns = self._get_ignore_patterns()
        relevant_files = (
            [
                item
                for item in self.workspace.rglob("*")
                if item.is_file()
                and item != self.settings_file
                and self._is_file_ignored(item.name, patterns) is None
            ]
            if self.workspace.exists()
            else []
        )
        if not relevant_files:
            return {"is_empty": True, "file_count": 0, "size_mb": 0.0}

        total_size = sum(item.stat().st_size for item in relevant_files)

        return {
            "is_empty": False,
            "file_count": len(relevant_files),
            "size_mb": round(total_size / BYTES_PER_MB, 2),
        }

    def _build_content_entry(self, path: Path) -> tuple[str, str, float]:
        """Baut (relativer_pfad, Anzeigetext, mtime) für einen Datei- oder Punkt-Ordner-Eintrag.

        Bei Verzeichnissen (Punkt-Ordner) wird die Größe rekursiv aus allen
        enthaltenen Dateien summiert, statt den Ordnerinhalt einzeln aufzulisten.
        """
        rel_path = str(path.relative_to(self.workspace))
        if path.is_dir():
            size = sum(
                item.stat().st_size for item in path.rglob("*") if item.is_file()
            )
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
        """Dateiliste für curses_browse(), neueste zuerst.

        Nutzt os.walk() statt rglob(), damit Punkt-Ordner (z. B. .git) gezielt von
        der Rekursion ausgeschlossen werden können (dirnames-Pruning in-place) und
        als ein Eintrag mit rekursiv berechneter Gesamtgröße erscheinen statt mit
        ihrem vollständigen Inhalt gelistet zu werden.
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
        """Löscht eine Datei oder ein Verzeichnis rekursiv."""
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

    def _get_ignore_patterns(self, extra_key: str | None = None) -> list[str]:
        """Kombiniert die globale ignore_patterns-Basisliste mit optionalen Zusatz-Patterns
        unter extra_key (z. B. "export_ignore_patterns"); None liefert nur die Basisliste."""
        if not self.config_manager:
            return []
        base = self.config_manager.config.get("ignore_patterns", [])
        extra = self.config_manager.config.get(extra_key, []) if extra_key else []
        return [*base, *extra]

    def _get_exclude_args(self, pattern_key: str) -> list[str]:
        """Baut rsync --exclude-Argumente aus globalen + kontextspezifischen Ignore-Patterns."""
        return [
            f"--exclude={pattern}"
            for pattern in self._get_ignore_patterns(pattern_key)
        ]

    @staticmethod
    def _run_rsync(cmd: list[str]) -> None:
        """Führt einen rsync-Befehl aus.

        Raises:
            OSError: Wenn rsync fehlt oder mit Fehler endet (z. B. SSH nicht erreichbar).
        """
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise OSError("rsync wurde nicht gefunden (Installation prüfen)") from e
        if result.returncode != 0:
            stderr = result.stderr.strip() or "unbekannter Fehler"
            raise OSError(f"rsync fehlgeschlagen (Exit {result.returncode}): {stderr}")

    def _rsync_mirror(
        self,
        source: Path | str,
        destination: Path | str,
        pattern_key: str,
        delete_excluded: bool,
    ) -> None:
        """Spiegelt source nach destination via rsync (überträgt auch Löschungen)."""
        cmd = [RSYNC_BINARY, *RSYNC_BASE_ARGS]
        if delete_excluded:
            cmd.append(RSYNC_DELETE_EXCLUDED_ARG)
        cmd.extend(self._get_exclude_args(pattern_key))
        cmd.extend([f"{source}/", str(destination)])
        self._run_rsync(cmd)

    def _rsync_copy_file(self, source: Path | str, destination: Path | str) -> None:
        """Kopiert eine einzelne Datei via rsync (lokal wie remote) statt shutil.copy2."""
        self._run_rsync([RSYNC_BINARY, *RSYNC_FILE_COPY_ARGS, str(source), str(destination)])

    @staticmethod
    def _is_file_ignored(filename: str, patterns: list[str]) -> str | None:
        """Erstes zutreffendes fnmatch-Pattern, oder None."""
        return next(
            (pattern for pattern in patterns if fnmatch.fnmatch(filename, pattern)),
            None,
        )

    def needs_overwrite_confirmation(self) -> bool:
        """True wenn vor einem Überschreiben nachgefragt werden soll (dont_ask_on_export_overwrite=False)."""
        dont_ask = (
            self.config_manager.config.get("dont_ask_on_export_overwrite", False)
            if self.config_manager
            else False
        )
        return not dont_ask

    def matched_ignore_pattern(self, filename: str, pattern_key: str) -> str | None:
        """Erstes zutreffendes Ignore-Pattern für filename unter pattern_key, oder None."""
        return self._is_file_ignored(filename, self._get_ignore_patterns(pattern_key))

    def reset(self) -> bool:
        """Löscht Workspace vollständig (alle Dateien und Verzeichnisse)."""
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

    def export_to(self, destination: Path | str) -> OperationResult:
        """Exportiert Workspace zu destination (Folder Mode, rsync-Mirror).

        destination als str bedeutet ein SSH-Remote-Ziel (z. B. "user@host:/pfad") und
        wird unverändert an rsync durchgereicht statt als lokaler Path interpretiert.
        Existenz-/Überschreib-Checks und die Reset-Nachfrage danach sind Sache des
        Aufrufers (LauncherApp) – diese Methode führt nur den Sync aus.
        """
        try:
            self._rsync_mirror(
                self.workspace, destination, "export_ignore_patterns", delete_excluded=False
            )
            print(f"✓ Erfolgreich exportiert nach: {destination}")
            return OperationResult(success=True)
        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return OperationResult(success=False, error=str(e))
        except OSError as e:
            print(f"✗ Fehler beim Export: {e}")
            return OperationResult(success=False, error=str(e))

    def export_file_to(self, rel_file_path: str, destination: Path | str) -> OperationResult:
        """Exportiert eine einzelne Datei aus Workspace nach destination (lokal oder SSH-Remote).

        Ignore-Pattern-Warnung ist Sache des Aufrufers (matched_ignore_pattern()).
        """
        source_file = self.workspace / rel_file_path

        if not source_file.exists():
            return OperationResult(False, f"Datei nicht gefunden:\n{source_file}")

        try:
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
            self._rsync_copy_file(source_file, destination)
            return OperationResult(success=True)
        except PermissionError as e:
            return OperationResult(False, f"Keine Berechtigung:\n{e}")
        except OSError as e:
            return OperationResult(False, f"Fehler beim Export:\n{e}")

    def import_file_from(self, source_file: Path | str) -> OperationResult:
        """Importiert eine einzelne Datei nach Workspace-Root (lokal oder SSH-Remote).

        Der Not-Found-Guard greift nur bei lokaler source_file – ein Remote-Pfad kann
        ohne SSH-Verbindung nicht vorab geprüft werden, ein nicht erreichbares Ziel
        schlägt stattdessen als OSError beim rsync-Aufruf fehl.
        """
        if isinstance(source_file, Path) and not source_file.exists():
            return OperationResult(False, f"Quelldatei nicht gefunden:\n{source_file}")

        filename = (
            source_file.name
            if isinstance(source_file, Path)
            else PurePosixPath(_remote_path_part(source_file)).name
        )
        try:
            destination = self.workspace / filename
            self._rsync_copy_file(source_file, destination)
            return OperationResult(success=True)
        except PermissionError as e:
            return OperationResult(False, f"Keine Berechtigung:\n{e}")
        except OSError as e:
            return OperationResult(False, f"Fehler beim Import:\n{e}")

    def import_from(self, source: Path | str) -> OperationResult:
        """Importiert Workspace von source (Folder Mode, rsync-Mirror inkl. Löschungen).

        source als str bedeutet ein SSH-Remote-Ziel und wird unverändert an rsync
        durchgereicht. Existenz-/Verzeichnis-Checks und die "Workspace nicht leer"-
        Bestätigung sind Sache des Aufrufers (LauncherApp) – diese Methode führt nur
        den Sync aus.
        """
        try:
            self._rsync_mirror(
                source, self.workspace, "import_ignore_patterns", delete_excluded=True
            )
            print(f"✓ Erfolgreich importiert von: {source}")
            return OperationResult(success=True)
        except PermissionError as e:
            print(f"✗ Keine Berechtigung: {e}")
            return OperationResult(success=False, error=str(e))
        except OSError as e:
            print(f"✗ Fehler beim Import: {e}")
            return OperationResult(success=False, error=str(e))
