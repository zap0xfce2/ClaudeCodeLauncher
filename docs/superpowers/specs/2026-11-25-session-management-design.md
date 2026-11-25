# Session-Management – Design (kurz)

## Warum

Mehrere Launcher-Instanzen laufen parallel. Eine Instanz zeigt groß den Namen der aktiven Session an (Banner), eine andere startet Claude mit diesem Namen (`claude --name <session>`, entspricht `/rename`). Die aktive Session ist der gemeinsame Zustand in `config.toml`.

## Ziele

- Session-Namen in `config.toml` speichern, auswählen, bearbeiten, löschen
- Auswahl einer Session → aktiv setzen + Vollbild-Banner anzeigen
- `ESC` im Banner → Banner schließen, keine Session mehr aktiv
- „Sitzung starten" hängt bei aktiver Session `--name <session>` an

## Nicht-Ziele

- Kein Resume/`--continue` einer benannten Session
- Kein Locking zwischen Instanzen (bestehendes `reload()`-Muster reicht)
- Kein Resize-Redraw des Banners

## Ansätze

1. **Banner außerhalb von curses, Logik von `banner.sh` nach Python portiert** – gewählt. Optik identisch zu `banner.sh` (figlet + lolcat), wenig Code, gleiches Muster wie `launch_claude()`.
2. Banner innerhalb von curses – sauberer Resize, aber kein lolcat (curses rendert dessen ANSI nicht), eigener Farbverlauf nötig, mehr Code.
3. `banner.sh` direkt aufrufen – verworfen: endet bei jeder Taste statt nur `ESC`, Skript müsste neben das Nuitka-Binary.

## Design

**Config** (`config_manager.py`, Defaults): `sessions: list[str] = []`, `active_session: str = ""`.

**ConfigManager**: `add_session(name)` (dedupliziert, neueste zuerst), `rename_session(old, new)` (leerer `new` = löschen), `set_active_session(name)` (`""` = keine). Jeweils `reload()` als erster Schritt (Multi-Instanz-Sicherheit).

**Menü**: „🧭 Importquelle in VS Code öffnen" entfällt komplett (Menüeintrag, Hotkey `v`, `handle_open_import_source()`, `VSCODE_BINARY`, Einträge in `SHORTCUT_LABELS`/`ACTION_TO_SHORTCUT`). Neu an derselben Stelle: „🔖 Sessions" (Action `sessions`, Hotkey `n`, getrackt im Footer).

**Auswahl** (`LauncherApp.handle_sessions()`): `curses_select(..., allow_edit=True)` wie `select_path_with_history()`. Einträge = `sessions` + „📝 Neue Session anlegen". `Enter` → `set_active_session()` + Banner. `Tab` → `curses_input()` vorausgefüllt → `rename_session()`. Neu anlegen → `add_session()` + direkt aktivieren + Banner.

**Banner** (neues Modul `session_banner.py`, keine internen Importe außer `constants`): `show_session_banner(name)` – `clear`, `figlet -c -w <cols> <name>` per subprocess, vertikal zentrieren (`shutil.get_terminal_size()`), Ausgabe durch `lolcat` pipen, Cursor verstecken, im Raw-Mode (`termios`/`tty`) auf `ESC` warten, im `finally` Cursor + Terminal-Mode wiederherstellen. Fallback: ohne `lolcat` → figlet ungefärbt; ohne `figlet` → Name als zentrierter Klartext. Nach `ESC`: `set_active_session("")`.

**Start** (`launch_claude()`): `reload()`, bei nicht-leerem `active_session` `["--name", session]` vor dem `--`-Instruction-Separator anhängen.

**Status-Spalte**: bei aktiver Session zusätzliche Zeile `🔖 <session>`.

**Tests**: Session-Methoden des `ConfigManager`; Banner-Zentrierungsrechnung als reine Funktion (`_banner_top_offset(rows, art_height)`). Terminal-IO manuell.

**Doku**: `CLAUDE.md` + `Readme.md` (Config-Keys, Hotkey `n`, `v` entfernt, `figlet`/`lolcat` als optionale Abhängigkeiten).

## Calls des Builders (von Claude gesetzt, korrigierbar)

- Hotkey `n` (Name), Emoji 🔖 (Default Emoji Presentation, kein FE0F)
- Leerer Name beim Bearbeiten = Session löschen
- Neu angelegte Session wird sofort aktiv + Banner
- `ESC`-Erkennung: einzelnes `\x1b` ohne Folgebytes (kurzes `select`-Timeout), damit Pfeiltasten (Escape-Sequenzen) den Banner nicht beenden
