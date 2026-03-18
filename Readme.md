# Claude Code Launcher

Curses-basierter Terminal-Launcher für das Management von Claude Code Sessions. Vereinfacht das Backup, Wiederherstellen und Wechseln zwischen verschiedenen Workspace-Verzeichnissen.

## Features

- **Session-Management** – Neue Session starten oder bestehende fortsetzen
- **Export / Import** – Workspace als Backup sichern und wiederherstellen
- **Single-File-Modus** – Einzelne Dateien exportieren oder importieren
- **History** – Zuletzt verwendete Pfade werden gespeichert und vorgeschlagen
- **Ignore-Patterns** – Konfigurierbare Filter für Export und Import (z. B. `.git`, `.env`)
- **Config-Hotkeys** – Optionen direkt im Hauptmenü togglen
- **Shell-Zugang** – Terminal im Workspace-Verzeichnis öffnen
- **Plan-Editor** – `Plan.md` direkt in `vi` öffnen oder erstellen
- **macOS-Theme-Sync** – Claude-Theme wird automatisch mit Dark/Light Mode synchronisiert

## Voraussetzungen

- Python 3.10+
- `pyyaml >= 6.0.0`
- [Task](https://taskfile.dev) (nur für den Build)
- [PyInstaller](https://pyinstaller.org) (nur für den Build)

## Installation & Setup

```bash
pip install -r requirements.txt
```

### Binary erstellen (optional)

```bash
task build
```

Erstellt via PyInstaller eine eigenständige Binary unter `/opt/homebrew/bin/ClaudeCodeLauncher`.

## Verwendung

## Was ist ein Workspace

**Workspace** ist das Arbeitsverzeichnis einer Claude-Session – kein spezielles Konfigurationsverzeichnis. Es enthält projektspezifische Dateien wie `CLAUDE.md`, `Plan.md` oder `settings.local.json` und kann an beliebiger Stelle liegen (z. B. `/Users/alice/projects/meinem-workspace` oder `/Volumes/RamDisk/ClaudeCodeWorkspace`).

### Interaktiver Modus

Das ist der häufigste Verwendungsfall:

```bash
python ClaudeCodeLauncher.py /pfad/zu/meinem-workspace

# Mit benutzerdefinierter Config-Datei
python ClaudeCodeLauncher.py /pfad/zu/meinem-workspace --config /pfad/zur/config.yaml
```

`config.yaml` wird standardmäßig im selben Verzeichnis wie `ClaudeCodeLauncher.py` angelegt. Das geöffnete Workspace-Verzeichnis wird im Hauptmenü oben rechts angezeigt.

### Direkt-Modus (ohne Menü)

```bash
# Exportieren
python ClaudeCodeLauncher.py /pfad/zu/meinem-workspace --export /pfad/zum/backup

# Importieren
python ClaudeCodeLauncher.py /pfad/zu/meinem-workspace --import /pfad/zum/backup

# Mit benutzerdefiniertem Claude Binary
python ClaudeCodeLauncher.py /pfad/zu/meinem-workspace --claude-binary /usr/local/bin/claude
```

**Single-File-Erkennung** erfolgt automatisch:

- `--export /tmp/datei.json` → Dateiauswahl aus Workspace, Export als einzelne Datei
- `--export /tmp/backup` → Folder-Modus (komplettes Workspace)

### Alle CLI-Argumente

| Argument               | Beschreibung                                                             |
| ---------------------- | ------------------------------------------------------------------------ |
| `workspace`            | Pfad zum Arbeitsverzeichnis der Claude-Session (Workspace) **(Pflicht)** |
| `--export PATH`        | Exportiert Workspace direkt zum angegebenen Pfad                         |
| `--import PATH`        | Importiert Workspace direkt vom angegebenen Pfad                         |
| `--config PATH`        | Pfad zur Config-Datei (Standard: `./config.yaml`)                        |
| `--claude-binary PATH` | Pfad zum Claude Binary (Standard: automatische Erkennung via PATH)       |

## Konfiguration

Die Datei `config.yaml` wird automatisch im Script-Verzeichnis erstellt und kann manuell bearbeitet werden.

| Option                         | Typ    | Standard | Beschreibung                                                                            |
| ------------------------------ | ------ | -------- | --------------------------------------------------------------------------------------- |
| `max_history_entries`          | int    | `10`     | Maximale Anzahl an History-Einträgen                                                    |
| `history`                      | Liste  | `[]`     | Gespeicherte Export/Import-Pfade mit Timestamps                                         |
| `export_ignore_patterns`       | Liste  | `[]`     | Dateimuster, die beim Export übersprungen werden                                        |
| `import_ignore_patterns`       | Liste  | `[]`     | Dateimuster, die beim Import übersprungen werden                                        |
| `claude_env`                   | Dict   | `{}`     | Umgebungsvariablen für Claude beim Start (z. B. `{ANTHROPIC_MODEL: "claude-opus-4-6"}`) |
| `ask_for_reset`                | bool   | `true`   | Nach Folder-Export: Fragen ob Workspace zurückgesetzt werden soll                       |
| `dont_ask_on_export_overwrite` | bool   | `false`  | Überschreib-Bestätigung beim Export unterdrücken                                        |
| `last_reset_timestamp`         | string | –        | Zeitstempel des letzten Resets (automatisch gesetzt, nicht manuell ändern)              |

**Empfohlene Ignore-Patterns:**

```yaml
export_ignore_patterns:
  - ".*"
  - ".git"
  - ".env"
  - "*.pyc"
  - "__pycache__"
```

## Tastenkürzel

### Hauptmenü

| Taste                 | Aktion                                 |
| --------------------- | -------------------------------------- |
| `↑` / `↓` / `j` / `k` | Navigation                             |
| `Tab` / `Shift+Tab`   | Navigation (vor/zurück)                |
| `Enter` / `Space`     | Auswählen                              |
| `r`                   | Status aktualisieren                   |
| `s`                   | Shell direkt öffnen                    |
| `x`                   | `ask_for_reset` togglen                |
| `o`                   | `dont_ask_on_export_overwrite` togglen |
| `q`                   | Beenden                                |

### Ja/Nein-Dialoge

| Taste                 | Aktion                    |
| --------------------- | ------------------------- |
| `←` / `→` / `h` / `l` | Zwischen Ja/Nein wechseln |
| `Tab`                 | Zwischen Ja/Nein wechseln |
| `Enter` / `Space`     | Bestätigen                |
| `y`                   | Direkt Ja                 |
| `j` / `n`             | Direkt Nein               |
| `ESC`                 | Abbrechen (= Nein)        |

### Listen-Auswahl

| Taste                               | Aktion                                                               |
| ----------------------------------- | -------------------------------------------------------------------- |
| `↑` / `↓` / `j` / `k` / `Shift+Tab` | Navigation                                                           |
| `Tab`                               | Navigation nach unten (Standard) / Edit-Dialog öffnen (Pfad-Auswahl) |
| `Enter`                             | Auswahl bestätigen (Pfad-Auswahl: direkt übernehmen ohne Edit)       |
| `ESC` / `q`                         | Abbrechen                                                            |

Im Pfad-Auswahlmodus (`allow_edit`) öffnet `Tab` einen vorausgefüllten Edit-Dialog; `Enter` übernimmt den Pfad direkt.

### Inhalt anzeigen

| Taste                               | Aktion                |
| ----------------------------------- | --------------------- |
| `↑` / `↓` / `j` / `k` / `Shift+Tab` | Scrollen (nach oben)  |
| `Tab`                               | Scrollen (nach unten) |
| `ESC`                               | Zurück                |
