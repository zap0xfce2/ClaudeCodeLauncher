# Claude Code Launcher

Curses-basierter Terminal-Launcher für das Management von Claude Code Sessions. Vereinfacht das Backup, Wiederherstellen und Wechseln zwischen verschiedenen Workspace-Verzeichnissen.

## Motivation

Ich wollte Claude Code nicht direkt in meinen Projekten rumfuhrwerken lassen und auch jenseits von Git Änderungen tracken. Mit diesem Tool wurde die Möglichkeit geschaffen, mein Projekt in einem weiteren separaten Ordner zu halten, ganz ohne dass Claude Code meine Git History kennt. Das Management sollte dabei sehr einfach sein.

## Features

- **Session-Management** – Neue Session im Workspace starten
- **Export / Import** – Workspace als Backup sichern und wiederherstellen (Folder-Modus via `rsync`: Löschungen im Workspace werden ins Exportziel übertragen); jeder Export warnt, wenn das Ziel vom letzten Import-Pfad abweicht
- **Single-File-Modus** – Einzelne Dateien exportieren oder importieren
- **History** – Zuletzt verwendete Pfade werden gespeichert und vorgeschlagen
- **VS-Code-Sprung** – Importquelle (letzter Import-Pfad) direkt in VS Code öffnen
- **Ignore-Patterns** – Konfigurierbare Filter für Export und Import (z. B. `.git`, `.env`)
- **Config-Hotkeys** – Optionen direkt im Hauptmenü togglen
- **Shortcut-Cheatsheet** – Taste `h` zeigt eine Vollbild-Übersicht aller Shortcuts, schließt sich bei jedem beliebigen Tastendruck wieder
- **Dynamischer Footer** – zeigt neben `[h]`/`[q]` die vier zuletzt verwendeten Shortcuts, sitzungsübergreifend in `config.toml` gemerkt
- **Maus-Navigation** – Hover wechselt die Auswahl, Klick bestätigt (Hauptmenü, Ja/Nein-Dialoge, Listen-Auswahl, Workspace-Inhalt anzeigen); per `config.toml` ab-/anschaltbar
- **Workspace-Übersicht** – Mehrspaltige, nach letzter Änderung sortierte Dateiliste für schnelle Projekterkennung in breiten Terminal-Fenstern; Punkt-Ordner (z. B. `.git`) erscheinen als ein Eintrag mit rekursiv berechneter Gesamtgröße statt mit ihrem vollständigen Inhalt; 📁/📄-Symbole unterscheiden Ordner- und Datei-Einträge
- **Shell-Zugang** – Terminal im Workspace-Verzeichnis öffnen
- **Plan-Editor** – `Plan.md` direkt in `vi` öffnen oder erstellen
- **macOS-Theme-Sync** – Claude-Theme wird automatisch mit Dark/Light Mode synchronisiert
- **Claude-Nutzungsstatistik** – Session-/Weekly-Auslastung samt "Aktualisiert"-Zeitstempel via `openusage`-CLI (falls installiert); wird in `config.toml` zwischengespeichert, sodass sie auch bei einer fehlgeschlagenen Neu-Abfrage sichtbar bleibt

## Voraussetzungen

- Python 3.11+
- `rsync` (für Folder-Export/-Import; auf macOS vorinstalliert)
- `code`-CLI von VS Code (optional, nur für „Importquelle in VS Code öffnen")
- [Task](https://taskfile.dev) (nur für den Build)
- [uv](https://docs.astral.sh/uv/) (Dependency-Management; installiert auch [Nuitka](https://nuitka.net) für den Build)

## Installation & Setup

```bash
uv sync
```

### Binary erstellen (optional)

```bash
task build
```

Erstellt via Nuitka eine eigenständige Binary unter `/opt/homebrew/bin/ClaudeCodeLauncher`.

## Verwendung

### Was ist ein Workspace?

**Workspace** ist das Arbeitsverzeichnis einer Claude-Session – kein spezielles Konfigurationsverzeichnis. Es enthält projektspezifische Dateien wie `CLAUDE.md`, `Plan.md` oder `settings.local.json` und kann an beliebiger Stelle liegen (z. B. `/Users/alice/projects/meinem-workspace` oder `/Volumes/RamDisk/ClaudeCodeWorkspace`).

### Interaktiver Modus

Das ist der häufigste Verwendungsfall:

```bash
./ClaudeCodeLauncher /pfad/zu/meinem-workspace

# Mit benutzerdefinierter Config-Datei
./ClaudeCodeLauncher /pfad/zu/meinem-workspace --config /pfad/zur/config.toml
```

`config.toml` wird standardmäßig im selben Verzeichnis wie `ClaudeCodeLauncher` angelegt. Das geöffnete Workspace-Verzeichnis wird im Hauptmenü oben rechts angezeigt.

### Direkt-Modus (ohne Menü)

```bash
# Exportieren
./ClaudeCodeLauncher /pfad/zu/meinem-workspace --export /pfad/zum/backup

# Importieren
./ClaudeCodeLauncher /pfad/zu/meinem-workspace --import /pfad/zum/backup

# Mit benutzerdefiniertem Claude Binary
./ClaudeCodeLauncher /pfad/zu/meinem-workspace --claude-binary /usr/local/bin/claude
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
| `--config PATH`        | Pfad zur Config-Datei (Standard: `./config.toml`)                        |
| `--claude-binary PATH` | Pfad zum Claude Binary (Standard: automatische Erkennung via PATH)       |

## Konfiguration

Die Datei `config.toml` wird automatisch im Script-Verzeichnis erstellt und kann manuell bearbeitet werden.

| Option                         | Typ    | Standard | Beschreibung                                                                                                                            |
| ------------------------------ | ------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `max_history_entries`          | int    | `10`     | Maximale Anzahl an History-Einträgen                                                                                                    |
| `history`                      | Liste  | `[]`     | Gespeicherte Export/Import-Pfade mit Timestamps                                                                                         |
| `export_ignore_patterns`       | Liste  | `[]`     | Dateimuster, die beim Export übersprungen werden; passende Einträge im Exportziel (z. B. dessen `.git`/`.env`) bleiben unangetastet     |
| `import_ignore_patterns`       | Liste  | `[]`     | Dateimuster, die beim Import übersprungen werden                                                                                        |
| `claude_env`                   | Dict   | `{}`     | Umgebungsvariablen für Claude beim Start (z. B. `{ANTHROPIC_MODEL: "claude-opus-4-6"}`)                                                 |
| `claude_instruction`           | string | `""`     | Anweisung, die beim Start automatisch als erster Prompt an Claude übergeben wird (leer = keine)                                         |
| `ask_for_reset`                | bool   | `true`   | Nach Folder-Export: Fragen ob Workspace zurückgesetzt werden soll                                                                       |
| `dont_ask_on_export_overwrite` | bool   | `false`  | Überschreib-Bestätigung beim Export unterdrücken                                                                                        |
| `plan_idle_timer_enabled`      | bool   | `true`   | Automatischer Menü-Refresh bei Änderung von `.Plan.md.swp` (nur Hauptmenü). Kein Hotkey, nur `config.toml`                              |
| `plan_idle_timer_duration`     | int    | `10`     | Poll-Intervall in Sekunden für den Plan-Idle-Timer                                                                                      |
| `mouse_navigation_enabled`     | bool   | `true`   | Maus-Hover/Klick in Hauptmenü, Ja/Nein-Dialogen, Listen-Auswahl und Workspace-Inhalt anzeigen                                           |
| `recent_shortcuts`             | Liste  | `[]`     | Zuletzt verwendete Hotkey-Buchstaben (neuestes zuerst, max. 4), bestimmt den dynamischen Footer-Ausschnitt. Automatisch gepflegt        |
| `usage_cache`                  | Dict   | `{}`     | Zwischengespeicherte Claude-Nutzungsstatistik der letzten erfolgreichen `openusage`-Abfrage. Automatisch gepflegt, nicht manuell ändern |
| `last_reset_timestamp`         | string | –        | Zeitstempel des letzten Resets (automatisch gesetzt, nicht manuell ändern)                                                              |

`claude_instruction` wird manuell in `config.toml` gepflegt; eine Änderung wirkt nach Drücken von `r` (Refresh) im Hauptmenü, ohne den Launcher neu zu starten.

**Empfohlene Ignore-Patterns:**

```toml
export_ignore_patterns = [".*", ".git", ".env", "*.pyc", "__pycache__"]
```

## Tastenkürzel

### Hauptmenü

| Taste               | Aktion                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------- |
| `↑` / `↓`           | Navigation                                                                                                    |
| `Tab` / `Shift+Tab` | Navigation (vor/zurück)                                                                                       |
| Maus-Hover          | Auswahl wechselt zum Eintrag unter dem Zeiger (siehe `mouse_navigation_enabled`)                              |
| Maus-Klick          | Eintrag auswählen (= Enter)                                                                                   |
| `Enter` / `Space`   | Auswählen                                                                                                     |
| `h`                 | Shortcut-Cheatsheet anzeigen (alle Shortcuts, schließt bei beliebiger Taste)                                  |
| `r`                 | Status aktualisieren                                                                                          |
| `s`                 | Sitzung starten                                                                                               |
| `t`                 | Shell direkt öffnen                                                                                           |
| `p`                 | Plan schreiben (`Plan.md` in `vi` öffnen/erstellen)                                                           |
| `e`                 | Export zum ersten Export-History-Eintrag (wie jeder Export: warnt, wenn der Pfad vom letzten Import abweicht) |
| `i`                 | Import vom ersten Import-History-Eintrag (mit bestehender Lösch-Rückfrage)                                    |
| `v`                 | Importquelle in VS Code öffnen                                                                                |
| `x`                 | `ask_for_reset` togglen (nicht mehr im Footer, nur im Cheatsheet)                                             |
| `o`                 | `dont_ask_on_export_overwrite` togglen (nicht mehr im Footer, nur im Cheatsheet)                              |
| `q`                 | Beenden                                                                                                       |

Der Footer zeigt neben `[h]`/`[q]` dynamisch die vier zuletzt verwendeten Shortcuts (siehe `recent_shortcuts`).

### Ja/Nein-Dialoge

| Taste             | Aktion                                       |
| ----------------- | -------------------------------------------- |
| `←` / `→`         | Zwischen Ja/Nein wechseln                    |
| `Tab`             | Zwischen Ja/Nein wechseln                    |
| Maus-Hover        | Auswahl wechselt zu Ja/Nein unter dem Zeiger |
| Maus-Klick        | Auswahl unter dem Zeiger sofort bestätigen   |
| `Enter` / `Space` | Bestätigen                                   |
| `y` / `j`         | Direkt Ja                                    |
| `n`               | Direkt Nein                                  |
| `ESC`             | Abbrechen (= Nein)                           |

### Listen-Auswahl

| Taste                   | Aktion                                                               |
| ----------------------- | -------------------------------------------------------------------- |
| `↑` / `↓` / `Shift+Tab` | Navigation                                                           |
| `Tab`                   | Navigation nach unten (Standard) / Edit-Dialog öffnen (Pfad-Auswahl) |
| Maus-Hover              | Auswahl wechselt zum Eintrag unter dem Zeiger                        |
| Maus-Klick              | Auswahl bestätigen (= Enter, öffnet nicht den Edit-Dialog)           |
| `Enter`                 | Auswahl bestätigen (Pfad-Auswahl: direkt übernehmen ohne Edit)       |
| `ESC` / `q`             | Abbrechen                                                            |

Im Pfad-Auswahlmodus (`allow_edit`) öffnet `Tab` einen vorausgefüllten Edit-Dialog; `Enter` übernimmt den Pfad direkt.

### Inhalt anzeigen

Mehrspaltige (`ls`-artige) Dateiliste, Spaltenzahl dynamisch nach Terminalbreite; sortiert nach letzter Änderung (neueste Dateien zuerst, oben links).

| Taste                   | Aktion                                        |
| ----------------------- | --------------------------------------------- |
| `↑` / `↓` / `Shift+Tab` | Scrollen (nach oben)                          |
| `Tab`                   | Scrollen (nach unten)                         |
| `←` / `→`               | Spalte wechseln                               |
| Maus-Hover / Maus-Klick | Auswahl wechselt zum Eintrag unter dem Zeiger |
| `ESC`                   | Zurück                                        |
