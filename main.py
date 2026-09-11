#!/usr/bin/env python3
"""Claude Code Launcher - Session Management Tool für Workspace"""

VERSION = "vYYMMDDhhmm"

import argparse
import os
import shutil
import sys
from pathlib import Path

from claude_code_launcher.config_manager import ConfigManager
from claude_code_launcher.launcher_app import LauncherApp
from claude_code_launcher.remote_target import _is_remote_target
from claude_code_launcher.system_helpers import _load_login_shell_path


def _cli_target(raw: str | None) -> Path | str | None:
    """CLI-Pfad-Arg in Path (lokal) oder rohen String (SSH-Remote-Ziel) umwandeln."""
    if raw is None:
        return None
    return raw if _is_remote_target(raw) else Path(raw).absolute()


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
  %(prog)s /path/to/.claude --export user@host:/backup  # Export zu SSH-Remote-Ziel (rsync)
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
    # Explizit relativ zu main.py statt ConfigManager()-Fallback (Path(__file__).parent
    # von config_manager.py), damit config.toml beim kompilierten Binary im Verzeichnis
    # des Entry-Points landet statt im Paket-Ordner.
    default_config_path = Path(__file__).parent / "config.toml"
    config_manager = ConfigManager(
        Path(args.config) if args.config else default_config_path
    )

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

    export_path = _cli_target(args.export_path)
    import_path = _cli_target(args.import_path)

    app = LauncherApp(
        workspace,
        config_manager,
        claude_binary,
        VERSION,
        export_path=export_path,
        import_path=import_path,
    )
    app.run()


if __name__ == "__main__":
    main()
