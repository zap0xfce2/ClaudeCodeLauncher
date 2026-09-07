"""Alle Konstanten des Launchers – Farben, Layout, Keys, externe Binaries."""

import curses

# --- Curses Farb-Paar IDs ---
COLOR_PAIR_ORANGE = 1
COLOR_PAIR_GRAY = 2
COLOR_PAIR_GREEN = 3
COLOR_PAIR_YELLOW = 4

# --- xterm256-Farben mit 8-Color-Fallback ---
MIN_COLORS_FOR_XTERM256 = 256
CLAUDE_ORANGE_XTERM256_COLOR = 166  # Titel/Branding (~#DA7756)
CLAUDE_ORANGE_FALLBACK_COLOR = curses.COLOR_YELLOW
MENU_HIGHLIGHT_XTERM256_COLOR = 226  # aktive Auswahl
MENU_HIGHLIGHT_FALLBACK_COLOR = curses.COLOR_YELLOW
HINT_GRAY_XTERM256_COLOR = 245  # Status/Hints
HINT_GRAY_FALLBACK_COLOR = curses.COLOR_WHITE

# --- Key Codes ---
KEY_TAB = 9
KEY_ESC = 27
KEY_BACKSPACE_DEL = 127
KEY_SPACE = 32
KEY_PRINTABLE_MAX = 126

# XTerm Any-Event-Mouse-Tracking manuell schalten, da curses.mousemask() mit
# REPORT_MOUSE_POSITION dies bei Apples mitgelieferter libncurses (5.4) nicht
# zuverlässig ans Terminal übersetzt (keine Bewegungs-Events ohne Klick).
XTERM_ENABLE_MOUSE_MOTION_TRACKING = "\x1b[?1003h"
XTERM_DISABLE_MOUSE_MOTION_TRACKING = "\x1b[?1003l"

# --- UI Layout ---
MENU_TITLE_ROW = 1
MENU_SEPARATOR_ROW = 2
MENU_START_ROW = 4
UI_PADDING_X = 2
MENU_RIGHT_COL_BUFFER = 10
MENU_COLUMN_GAP_X = 4  # Abstand zwischen Menüspalte 1 und Spalte 2
MENU_ITEM_PREFIX_WIDTH = 2  # Breite von "> " bzw. "  " Präfix vor jedem Label
USAGE_STATS_COL_WIDTH = (
    26  # Reservierte Breite für die Claude-Nutzungsstatistik-Spalte ganz rechts
)
USAGE_STATS_MIN_GAP = MENU_COLUMN_GAP_X

# Spalten-Zuordnung für curses_menu(); muss mit Action-Keys aus LauncherApp.get_menu_items() übereinstimmen.
WORKFLOW_ACTIONS = frozenset({"plan", "start", "export", "import"})

# --- Footer / Cheatsheet ---
RECENT_SHORTCUTS_MAX_ENTRIES = 6
# Ein-Buchstaben-Hotkeys aus curses_menu() mit Anzeigetext, gemeinsame Quelle für
# Footer (dynamischer Ausschnitt) und Cheatsheet ([h], vollständige Liste).
SHORTCUT_LABELS: dict[str, str] = {
    "r": "Refresh",
    "s": "Sitzung starten",
    "t": "Shell",
    "e": "Quick Export",
    "i": "Quick Import",
    "v": "VS Code",
    "p": "Prompts verwalten",
    "x": "Nach Export zurücksetzen",
    "o": "Überschreiben bestätigen",
    "h": "Hilfe",
    "q": "Beenden",
}
# Menü-Actions (LauncherApp.handle_action()), deren Nutzung in recent_shortcuts getrackt wird.
ACTION_TO_SHORTCUT: dict[str, str] = {
    "start": "s",
    "shell": "t",
    "plan": "p",
    "export_first": "e",
    "import_first": "i",
    "open_import_source": "v",
}

# --- Dateigrößen ---
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024

# --- rsync (Folder-Mode Export/Import) ---
RSYNC_BINARY = "rsync"
RSYNC_BASE_ARGS = ["-a", "--delete"]
RSYNC_DELETE_EXCLUDED_ARG = "--delete-excluded"

# --- VS Code CLI (Importquelle öffnen) ---
VSCODE_BINARY = "code"

# --- macOS Theme-Erkennung (launch_claude) ---
DEFAULTS_BINARY = "defaults"

# --- proqi CLI (Prompt-Sessions durchsuchen, handle_prompt_sessions) ---
PROQI_BINARY = "proqi"

# --- Terminal leeren vor Claude-Start (launch_claude) ---
CLEAR_BINARY = "/usr/bin/clear"

# --- Shell / Login-Shell-PATH ---
DEFAULT_SHELL = "/bin/zsh"
LOGIN_SHELL_PATH_PROBE_TIMEOUT = 5
PATH_PROBE_START_MARKER = "__PATH_START__"
PATH_PROBE_END_MARKER = "__PATH_END__"

# --- openusage CLI (Claude-Nutzungsstatistik) ---
OPENUSAGE_BINARY = "openusage"
OPENUSAGE_PROVIDER = "claude"
# Unser usage_cache.expires_at ist 1:1 aus openusages eigenem expiresAt übernommen, daher
# trifft jeder Refresh zwangsläufig auf einen kalten (nicht gecachten) Abruf, nie einen
# warmen. Gemessener kalter Abruf: ~3.1s – 3s Timeout ließ Refreshes praktisch immer
# fehlschlagen und den Cache wochenlang einfrieren.
OPENUSAGE_FETCH_TIMEOUT = 10
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440

# --- Zwischenablage (Browse: Dateiname kopieren) ---
CLIPBOARD_BINARY = "pbcopy"
CLIPBOARD_COPY_TIMEOUT = 2

# --- Einrückung für Listen-Einträge (UI_PADDING_X + "> " Präfix) ---
ITEM_INDENT_X = UI_PADDING_X + 2  # = 4
