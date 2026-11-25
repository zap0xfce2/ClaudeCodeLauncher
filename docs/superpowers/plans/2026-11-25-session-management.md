# Session-Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Benannte Claude-Sessions in `config.toml` verwalten, aktive Session per Vollbild-Banner anzeigen und beim Start als `claude --name <session>` übergeben.

**Architecture:** `ConfigManager` bekommt Session-CRUD + `active_session`. Neues Modul `session_banner.py` portiert `banner.sh` (figlet/lolcat außerhalb von curses, Fallbacks). `LauncherApp` ersetzt den VS-Code-Menüpunkt durch „🔖 Sessions“ und hängt `--name` in `launch_claude()` an.

**Tech Stack:** Python 3.12 stdlib (`curses`, `termios`, `tty`, `select`, `subprocess`, `shutil`), pytest, go-task.

**Spec:** `docs/superpowers/specs/2026-11-25-session-management-design.md`

## Global Constraints

- Config-Keys exakt: `sessions` (Default `[]`), `active_session` (Default `""`)
- Claude-Parameter exakt: `--name <session>`, **vor** dem `--`-Instruction-Separator
- Menüeintrag exakt `("sessions", "🔖 Sessions")`, Hotkey `n`, Label `"n": "Sessions"`, `ACTION_TO_SHORTCUT["sessions"] = "n"`
- Neuer Auswahl-Eintrag exakt `("__custom__", "📝 Neue Session anlegen")`
- Jede ConfigManager-Mutation beginnt mit `self.reload()` (Multi-Instanz-Sicherheit)
- Alle UI-Texte Deutsch; `VERSION` in `main.py` nie anfassen
- CleanCode-Regeln aus `~/.claude/CLAUDE.md` (Type Hints, keine Magic Strings, ≤30 Zeilen/Funktion)
- Git: Feature-Branch `feat/session-management`, Conventional Commits, keine AI-Attribution

## Review Focus

- Session-Name mit Leerzeichen/Sonderzeichen (`meine session`, `über-ö`): muss als ein Argument an `claude` gehen (Liste statt Shell-String) → Test in Task 3
- Doppelter Name beim Anlegen/Umbenennen: keine Duplikate in `sessions` → Tests in Task 1
- Umbenennen der gerade aktiven Session: `active_session` folgt dem neuen Namen → Test in Task 1
- Löschen (leerer Name) der aktiven Session: `active_session` wird `""` → Test in Task 1
- Name nur aus Whitespace: wird wie leer behandelt (`strip()`) → Test in Task 1

---

### Task 1: ConfigManager – Sessions

**Files:**
- Modify: `claude_code_launcher/config_manager.py` (Defaults in `load_config()`, neue Methoden nach `record_shortcut_usage()`)
- Test: `tests/test_config_manager.py`

**Interfaces:**
- Produces: `add_session(name: str) -> None`, `rename_session(old: str, new: str) -> None`, `set_active_session(name: str) -> None`

- [ ] **Step 1: Failing Tests schreiben** (je ein Assert, `ConfigManager(tmp_path / "config.toml")`)

```python
def test_default_config_has_empty_sessions(tmp_path):
    assert ConfigManager(tmp_path / "config.toml").config["sessions"] == []

def test_default_config_has_no_active_session(tmp_path):
    assert ConfigManager(tmp_path / "config.toml").config["active_session"] == ""

def test_add_session_inserts_newest_first(tmp_path):
    m = ConfigManager(tmp_path / "config.toml"); m.add_session("a"); m.add_session("b")
    assert m.config["sessions"] == ["b", "a"]

def test_add_session_deduplicates(tmp_path):
    m = ...; m.add_session("a"); m.add_session("b"); m.add_session("a")
    assert m.config["sessions"] == ["a", "b"]

def test_add_session_strips_whitespace(tmp_path):
    m = ...; m.add_session("  a  ")
    assert m.config["sessions"] == ["a"]

def test_add_session_ignores_blank_name(tmp_path):
    m = ...; m.add_session("   ")
    assert m.config["sessions"] == []

def test_rename_session_replaces_in_place(tmp_path):
    m = ...; m.add_session("a"); m.add_session("b"); m.rename_session("a", "c")
    assert m.config["sessions"] == ["b", "c"]

def test_rename_session_to_existing_name_deduplicates(tmp_path):
    m = ...; m.add_session("a"); m.add_session("b"); m.rename_session("a", "b")
    assert m.config["sessions"] == ["b"]

def test_rename_session_with_blank_name_deletes(tmp_path):
    m = ...; m.add_session("a"); m.rename_session("a", "  ")
    assert m.config["sessions"] == []

def test_rename_active_session_updates_active(tmp_path):
    m = ...; m.add_session("a"); m.set_active_session("a"); m.rename_session("a", "c")
    assert m.config["active_session"] == "c"

def test_delete_active_session_clears_active(tmp_path):
    m = ...; m.add_session("a"); m.set_active_session("a"); m.rename_session("a", "")
    assert m.config["active_session"] == ""

def test_set_active_session_persists(tmp_path):
    path = tmp_path / "config.toml"; ConfigManager(path).set_active_session("a")
    assert ConfigManager(path).config["active_session"] == "a"
```

- [ ] **Step 2:** `uv run pytest tests/test_config_manager.py -v` → neue Tests FAIL (`KeyError`/`AttributeError`)
- [ ] **Step 3:** Defaults `"sessions": []`, `"active_session": ""` ergänzen; drei Methoden implementieren. `rename_session`: Liste ohne `new` bauen, `old` durch `new.strip()` ersetzen bzw. entfernen, wenn leer; `active_session == old` → auf neuen Namen bzw. `""` setzen. Jede Methode: `reload()` → mutieren → `save_config()`.
- [ ] **Step 4:** `task test` → alle PASS
- [ ] **Step 5:** Branch `feat/session-management` anlegen, commit `feat: store named claude sessions in config`

---

### Task 2: session_banner.py

**Files:**
- Create: `claude_code_launcher/session_banner.py`
- Modify: `claude_code_launcher/constants.py` (`FIGLET_BINARY = "figlet"`, `LOLCAT_BINARY = "lolcat"`, `ANSI_HIDE_CURSOR = "\x1b[?25l"`, `ANSI_SHOW_CURSOR = "\x1b[?25h"`, `ESC_SEQUENCE_TIMEOUT = 0.05`)
- Test: `tests/test_session_banner.py`

**Interfaces:**
- Consumes: Konstanten oben, `CLEAR_BINARY`
- Produces: `show_session_banner(name: str) -> None` (blockiert bis einzelnes `ESC`), `_banner_top_offset(rows: int, art_height: int) -> int`

- [ ] **Step 1: Failing Tests**

```python
def test_banner_top_offset_centers_vertically():
    assert _banner_top_offset(24, 6) == 9

def test_banner_top_offset_never_negative():
    assert _banner_top_offset(4, 10) == 0
```

- [ ] **Step 2:** `uv run pytest tests/test_session_banner.py -v` → FAIL (ImportError)
- [ ] **Step 3:** Implementieren, aufgeteilt in kleine Funktionen:
  - `_render_art(name, cols) -> str`: `figlet -c -w <cols> <name>` (`capture_output`, `text`); `FileNotFoundError`/Exit≠0 → `name.center(cols)`
  - `_print_colored(text) -> None`: `lolcat` mit `input=text`; `FileNotFoundError` → `print(text)`
  - `_wait_for_escape() -> None`: `tty.setcbreak` auf `sys.stdin`, Schleife `os.read(fd, 1)`; bei `b"\x1b"` prüft `select.select([fd], [], [], ESC_SEQUENCE_TIMEOUT)`: Folgebytes vorhanden → alle verfügbaren Bytes verwerfen, weiter warten; sonst return. `termios`-Settings im `finally` zurück.
  - `show_session_banner(name)`: `clear` → Größe via `shutil.get_terminal_size()` → Art rendern → `\n * top_offset` → farbig ausgeben → Cursor verstecken (nach lolcat, wie banner.sh) → warten; `finally`: Cursor zeigen + `clear`.
- [ ] **Step 4:** `task test` → PASS
- [ ] **Step 5:** commit `feat: add figlet/lolcat session banner`

---

### Task 3: LauncherApp – Menü, Auswahl, Start, Status; VS Code entfernen

**Files:**
- Modify: `claude_code_launcher/launcher_app.py` (`get_menu_items()`, `_build_status_text()`, `handle_open_import_source()` löschen, neu `handle_sessions()`, `launch_claude()`, `handle_action()`)
- Modify: `claude_code_launcher/ui_curses.py:544-545` (`v` → `n` liefert `"sessions"`)
- Modify: `claude_code_launcher/constants.py` (`VSCODE_BINARY` + Abschnitt löschen; `SHORTCUT_LABELS`/`ACTION_TO_SHORTCUT`: `v` raus, `n` rein)
- Test: `tests/test_launcher_app.py`

**Interfaces:**
- Consumes: Task 1 Methoden, `show_session_banner(name)`
- Produces: `LauncherApp._build_claude_command(claude_binary: Path, session: str, instruction: str) -> list[str]` (statisch)

- [ ] **Step 1: Failing Tests**

```python
def test_build_claude_command_without_session_or_instruction():
    assert LauncherApp._build_claude_command(Path("/c"), "", "") == ["/c"]

def test_build_claude_command_adds_name_before_instruction():
    assert LauncherApp._build_claude_command(Path("/c"), "meine session", "Hallo") == ["/c", "--name", "meine session", "--", "Hallo"]
```

- [ ] **Step 2:** `uv run pytest tests/test_launcher_app.py -v` → FAIL
- [ ] **Step 3:** `_build_claude_command` implementieren; `launch_claude()` ruft vorher `config_manager.reload()` und nutzt sie (`active_session`/`claude_instruction` je `.strip()`).
- [ ] **Step 4:** `handle_sessions()` nach Vorbild `select_path_with_history()`: Items `[(s, f"🔖 {s}") for s in sessions] + [("__custom__", "📝 Neue Session anlegen")]`, Titel `"Session auswählen:"`, `curses_select(..., allow_edit=True, mouse_enabled)`. `__custom__` → `curses_input("Session-Name eingeben:", "")` → `add_session` + aktivieren + Banner. `edit_mode` → `curses_input("Session-Name anpassen (leer = löschen):", selected)` → `rename_session`, kein Banner. Enter → aktivieren + Banner. Nach Banner `set_active_session("")`. Leere `sessions` → direkt Eingabe-Dialog.
- [ ] **Step 5:** Menü: `open_import_source`-Zeile durch `("sessions", "🔖 Sessions")` ersetzen; `handle_action`-Zweig tauschen; `handle_open_import_source()` + `VSCODE_BINARY`-Import löschen; `_build_status_text()` bei nicht-leerem `active_session` Zeile `"🔖 {session}\n"` nach der `📁`-Zeile einfügen.
- [ ] **Step 6:** `grep -rn "open_import_source\|VSCODE\|VS Code" claude_code_launcher tests` → keine Treffer; `uv run ruff check .` → sauber; `task test` → PASS
- [ ] **Step 7:** Manuell: Launcher starten, `n` → Session anlegen → Banner → zweite Instanz zeigt `🔖 name` nach `r`, `s` startet mit Namen; `ESC` im Banner → Statuszeile verschwindet nach `r`; Pfeiltaste im Banner beendet ihn nicht.
- [ ] **Step 8:** commit `feat: add session menu and pass --name to claude` (inkl. Entfernen VS Code)

---

### Task 4: Doku + Build

**Files:**
- Modify: `CLAUDE.md` (Modul-Liste + `session_banner.py`, Konstanten, ConfigManager-Methoden, LauncherApp `handle_sessions`/`_build_claude_command`, Config-Tabelle `sessions`/`active_session`, Hotkeys `n` statt `v`, Menü-Layout; alle VS-Code-Verweise entfernen)
- Modify: `Readme.md` (gleiche Punkte + `figlet`/`lolcat` als optionale Abhängigkeiten mit Fallback-Verhalten)

- [ ] **Step 1:** Beide Dateien aktualisieren; `grep -n "VS Code\|open_import_source\|\[v\]" CLAUDE.md Readme.md` → keine Treffer
- [ ] **Step 2:** `task` → Build + Install erfolgreich
- [ ] **Step 3:** commit `docs: document session management`, push, PR nach `master`, mergen, Branch löschen
