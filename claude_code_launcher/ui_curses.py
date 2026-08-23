"""Alle curses-UI-Funktionen und ihre Geometrie-/Render-Helfer. Reine Präsentationsschicht:
kein Wissen über ConfigManager/WorkspaceManager/LauncherApp, Datenfluss nur über Parameter."""

import curses
import os
import sys
from collections.abc import Callable
from typing import Literal, overload

from .constants import (
    CLAUDE_ORANGE_FALLBACK_COLOR,
    CLAUDE_ORANGE_XTERM256_COLOR,
    COLOR_PAIR_GRAY,
    COLOR_PAIR_GREEN,
    COLOR_PAIR_ORANGE,
    COLOR_PAIR_YELLOW,
    HINT_GRAY_FALLBACK_COLOR,
    HINT_GRAY_XTERM256_COLOR,
    ITEM_INDENT_X,
    KEY_BACKSPACE_DEL,
    KEY_ESC,
    KEY_PRINTABLE_MAX,
    KEY_SPACE,
    KEY_TAB,
    MENU_COLUMN_GAP_X,
    MENU_HIGHLIGHT_FALLBACK_COLOR,
    MENU_HIGHLIGHT_XTERM256_COLOR,
    MENU_ITEM_PREFIX_WIDTH,
    MENU_RIGHT_COL_BUFFER,
    MENU_SEPARATOR_ROW,
    MENU_START_ROW,
    MENU_TITLE_ROW,
    MIN_COLORS_FOR_XTERM256,
    SHORTCUT_LABELS,
    UI_PADDING_X,
    USAGE_STATS_COL_WIDTH,
    USAGE_STATS_MIN_GAP,
    WORKFLOW_ACTIONS,
    XTERM_DISABLE_MOUSE_MOTION_TRACKING,
    XTERM_ENABLE_MOUSE_MOTION_TRACKING,
)
from .system_helpers import _copy_to_clipboard


def _resolve_xterm256_color(xterm256_color: int, fallback_color: int) -> int:
    """Wählt xterm256_color bei 256-Color-Terminal-Support, sonst fallback_color."""
    return (
        xterm256_color if curses.COLORS >= MIN_COLORS_FOR_XTERM256 else fallback_color
    )


def _init_curses_colors(stdscr: "curses.window") -> None:
    """Initialisiert alle Curses Farb-Paare und setzt Cursor einmalig."""
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(
        COLOR_PAIR_ORANGE,
        _resolve_xterm256_color(
            CLAUDE_ORANGE_XTERM256_COLOR, CLAUDE_ORANGE_FALLBACK_COLOR
        ),
        -1,
    )
    curses.init_pair(
        COLOR_PAIR_GRAY,
        _resolve_xterm256_color(HINT_GRAY_XTERM256_COLOR, HINT_GRAY_FALLBACK_COLOR),
        -1,
    )
    curses.init_pair(COLOR_PAIR_GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(
        COLOR_PAIR_YELLOW,
        _resolve_xterm256_color(
            MENU_HIGHLIGHT_XTERM256_COLOR, MENU_HIGHLIGHT_FALLBACK_COLOR
        ),
        -1,
    )


def _is_up_key(key: int) -> bool:
    """True für KEY_UP oder Shift+Tab."""
    return key in (curses.KEY_UP, curses.KEY_BTAB)


def _is_down_key(key: int, include_tab: bool = True) -> bool:
    """True für KEY_DOWN, oder (wenn include_tab) Tab."""
    return key == curses.KEY_DOWN or (include_tab and key == KEY_TAB)


def _is_left_key(key: int) -> bool:
    """True für KEY_LEFT."""
    return key == curses.KEY_LEFT


def _is_right_key(key: int) -> bool:
    """True für KEY_RIGHT."""
    return key == curses.KEY_RIGHT


def _split_menu_columns(
    menu_items: list[tuple[str, str]],
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Teilt Menü-Items anhand WORKFLOW_ACTIONS in zwei Spalten auf.

    Gibt je Spalte (original_index, label) Tuples zurück – original_index verweist
    auf die Position in menu_items und bleibt so für Highlight/Navigation erhalten.
    """
    col1: list[tuple[int, str]] = []
    col2: list[tuple[int, str]] = []
    for i, (action, label) in enumerate(menu_items):
        target = col1 if action in WORKFLOW_ACTIONS else col2
        target.append((i, label))
    return col1, col2


def _swap_menu_column(
    current: int,
    col1: list[tuple[int, str]],
    col2: list[tuple[int, str]],
) -> int:
    """Wechselt current in die jeweils andere Spalte, möglichst gleiche Zeile (auf kürzere Spalte geklemmt)."""
    for row, (original_index, _label) in enumerate(col1):
        if original_index == current and col2:
            return col2[min(row, len(col2) - 1)][0]
    for row, (original_index, _label) in enumerate(col2):
        if original_index == current and col1:
            return col1[min(row, len(col1) - 1)][0]
    return current


def _render_menu_column(
    stdscr: "curses.window",
    column: list[tuple[int, str]],
    current: int,
    x: int,
    height: int,
) -> None:
    """Rendert eine Menüspalte an X-Position x, highlightet den Eintrag mit original_index == current."""
    for row, (original_index, label) in enumerate(column):
        y = MENU_START_ROW + row
        if y >= height - 2:
            break
        if original_index == current:
            stdscr.addstr(
                y, x, f"> {label}", curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD
            )
        else:
            stdscr.addstr(y, x, f"  {label}")


def _menu_column_hit_index(
    column: list[tuple[int, str]],
    x: int,
    label_width: int,
    mouse_y: int,
    mouse_x: int,
    height: int,
) -> int | None:
    """Hit-Test für eine Menüspalte; spiegelt exakt die Geometrie von _render_menu_column()."""
    row = mouse_y - MENU_START_ROW
    if row < 0 or row >= len(column):
        return None
    if MENU_START_ROW + row >= height - 2:
        return None
    item_width = MENU_ITEM_PREFIX_WIDTH + label_width
    if not (x <= mouse_x < x + item_width):
        return None
    return column[row][0]


def _menu_item_at_position(
    col1: list[tuple[int, str]],
    col2: list[tuple[int, str]],
    col1_x: int,
    col2_x: int,
    col1_label_width: int,
    col2_label_width: int,
    mouse_y: int,
    mouse_x: int,
    height: int,
) -> int | None:
    """Ermittelt den original_index des Menüeintrags unter dem Mauszeiger (beide Spalten)."""
    hit = _menu_column_hit_index(
        col1, col1_x, col1_label_width, mouse_y, mouse_x, height
    )
    if hit is not None:
        return hit
    return _menu_column_hit_index(
        col2, col2_x, col2_label_width, mouse_y, mouse_x, height
    )


def _select_item_at_position(
    items: list[tuple[str, str]], mouse_y: int, mouse_x: int, height: int
) -> int | None:
    """Hit-Test für curses_select(): einspaltige Liste ohne Scroll-Offset (anders als curses_browse())."""
    i = mouse_y - MENU_START_ROW
    if i < 0 or i >= len(items):
        return None
    if MENU_START_ROW + i >= height - 3:
        return None
    _, label = items[i]
    item_width = MENU_ITEM_PREFIX_WIDTH + len(label)
    if not (ITEM_INDENT_X <= mouse_x < ITEM_INDENT_X + item_width):
        return None
    return i


def _compute_browse_column_layout(
    items: list[tuple[str, str]], width: int
) -> tuple[int, int, int]:
    """Berechnet (num_columns, column_width, rows) fürs Grid in curses_browse().

    column_width enthält Präfix + Spaltenabstand; bei sehr langen Labels ergibt
    sich num_columns == 1 (Fallback auf Einzelspalten-Darstellung).
    """
    max_label_width = max((len(label) for _, label in items), default=0)
    column_width = max_label_width + MENU_ITEM_PREFIX_WIDTH + MENU_COLUMN_GAP_X
    available_width = width - UI_PADDING_X
    num_columns = max(1, min(len(items), available_width // column_width))
    rows = -(-len(items) // num_columns)  # ceil ohne math-Import
    return num_columns, column_width, rows


def _render_browse_columns(
    stdscr: "curses.window",
    items: list[tuple[str, str]],
    current: int,
    scroll_offset: int,
    num_columns: int,
    column_width: int,
    rows: int,
    list_start_y: int,
    viewport_height: int,
    height: int,
) -> None:
    """Rendert die Dateiliste column-major (wie `ls`: erst eine Spalte komplett, dann die nächste)."""
    label_width = column_width - MENU_ITEM_PREFIX_WIDTH - MENU_COLUMN_GAP_X
    for col in range(num_columns):
        x = UI_PADDING_X + col * column_width
        col_start = col * rows
        col_end = min(col_start + rows, len(items))
        for row in range(viewport_height):
            idx = col_start + scroll_offset + row
            if idx >= col_end:
                break
            y = list_start_y + row
            if y >= height - 2:
                break
            _, label = items[idx]
            display = label[:label_width]
            if idx == current:
                stdscr.addstr(
                    y,
                    x,
                    f"> {display}",
                    curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD,
                )
            else:
                stdscr.addstr(y, x, f"  {display}")


def _browse_grid_item_at_position(
    items: list[tuple[str, str]],
    num_columns: int,
    column_width: int,
    rows: int,
    scroll_offset: int,
    list_start_y: int,
    viewport_height: int,
    mouse_y: int,
    mouse_x: int,
    height: int,
) -> int | None:
    """Hit-Test für curses_browse(); spiegelt die Geometrie von _render_browse_columns() inkl. scroll_offset."""
    row = mouse_y - list_start_y
    if row < 0 or row >= viewport_height or list_start_y + row >= height - 2:
        return None
    if mouse_x < UI_PADDING_X:
        return None
    col = (mouse_x - UI_PADDING_X) // column_width
    if col >= num_columns:
        return None
    col_start = col * rows
    idx = col_start + scroll_offset + row
    if idx >= min(col_start + rows, len(items)):
        return None
    return idx


def _confirm_choice_at_position(
    choices: list[str], choice_x: int, y: int, mouse_y: int, mouse_x: int
) -> int | None:
    """Hit-Test für curses_confirm(): horizontale Zeile statt vertikaler Liste, kein Scroll-Check nötig."""
    if mouse_y != y:
        return None
    x = choice_x
    for i, choice in enumerate(choices):
        item_width = MENU_ITEM_PREFIX_WIDTH + len(choice)
        if x <= mouse_x < x + item_width:
            return i
        x += item_width + 2  # 2 = Trenner aus "  ".join() in curses_confirm()
    return None


def _render_cheatsheet(stdscr: "curses.window", height: int, width: int) -> None:
    """Vollbild-Shortcut-Übersicht (zweispaltig); bleibt sichtbar bis der Aufrufer die nächste Taste abfängt."""
    stdscr.clear()
    stdscr.addstr(
        MENU_TITLE_ROW,
        UI_PADDING_X,
        "Shortcuts",
        curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
    )
    sep = "─" * (width - 4)
    stdscr.addstr(
        MENU_SEPARATOR_ROW, UI_PADDING_X, sep, curses.color_pair(COLOR_PAIR_ORANGE)
    )

    lines = [f"[{key}] {label}" for key, label in SHORTCUT_LABELS.items()]
    split = -(-len(lines) // 2)  # ceil ohne math-Import
    col1, col2 = lines[:split], lines[split:]
    col1_width = max((len(line) for line in col1), default=0)
    col1_x = UI_PADDING_X
    col2_x = col1_x + col1_width + MENU_COLUMN_GAP_X

    for row, line in enumerate(col1):
        y = MENU_START_ROW + row
        if y >= height - 2:
            break
        stdscr.addstr(y, col1_x, line)
    if col2_x < width:
        for row, line in enumerate(col2):
            y = MENU_START_ROW + row
            if y >= height - 2:
                break
            stdscr.addstr(y, col2_x, line)

    if height > 3:
        stdscr.addstr(
            height - 2,
            UI_PADDING_X,
            "Beliebige Taste zum Schließen"[: width - 4],
            curses.color_pair(COLOR_PAIR_GRAY),
        )
    stdscr.refresh()


def _enable_mouse_tracking() -> None:
    """Aktiviert Klicks + XTerm-Motion-Tracking; REPORT_MOUSE_POSITION allein liefert unter
    Apples mitgelieferter libncurses (5.4) keine reinen Bewegungs-Events (kein Hover ohne Klick)."""
    curses.mousemask(curses.BUTTON1_CLICKED | curses.REPORT_MOUSE_POSITION)
    sys.stdout.write(XTERM_ENABLE_MOUSE_MOTION_TRACKING)
    sys.stdout.flush()


def _disable_mouse_tracking() -> None:
    """Deaktiviert Maus-Tracking; muss vor dem curses.wrapper()-Teardown erfolgen, sonst bleibt
    das Terminal bei manchen Emulatoren im Tracking-Modus (Escape-Sequenz-Müll in der Shell)."""
    sys.stdout.write(XTERM_DISABLE_MOUSE_MOTION_TRACKING)
    sys.stdout.flush()
    curses.mousemask(0)


def curses_menu(
    stdscr: "curses.window",
    banner_text: str,
    version_text: str,
    status_text: str,
    menu_items: list[tuple[str, str]],
    default_index: int = 0,
    idle_timeout_ms: int | None = None,
    idle_refresh_predicate: Callable[[], bool] | None = None,
    usage_stats_text: str | None = None,
    mouse_enabled: bool = True,
) -> str | None:
    """Hauptmenü: Banner+Version oben, zwei Menüspalten links, Status-Info rechts, optionaler Idle-Timer.

    idle_refresh_predicate liefert bei jedem Idle-Tick einen Vergleichswert; ändert er
    sich gegenüber dem Stand bei Funktionseintritt, wird erst dann ein Refresh ausgelöst
    (verhindert Flackern durch Refresh bei jedem Tick). None = jeder Tick refresht sofort.
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        _enable_mouse_tracking()
    current = default_index

    if idle_timeout_ms is not None:
        stdscr.timeout(idle_timeout_ms)

    initial_predicate_state = (
        idle_refresh_predicate() if idle_refresh_predicate is not None else None
    )

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            # Status-Text aufteilen: letzte Zeile = Footer, Rest = Info-Zeilen
            status_lines = status_text.split("\n")
            footer = status_lines[-1].strip() if status_lines else ""
            info_lines = [line.strip() for line in status_lines[:-1]]

            # Menü in zwei Spalten aufteilen (inhaltliche Gruppierung, siehe WORKFLOW_ACTIONS)
            col1, col2 = _split_menu_columns(menu_items)
            col1_label_width = max((len(label) for _, label in col1), default=0)
            col2_label_width = max((len(label) for _, label in col2), default=0)

            col1_x = UI_PADDING_X
            col2_x = (
                col1_x + col1_label_width + MENU_ITEM_PREFIX_WIDTH + MENU_COLUMN_GAP_X
            )

            # Rechte Spalte dynamisch: an rechte Menüspalte anschließen + Puffer für Emoji + Abstand
            status_anchor_x = col2_x if col2 else col1_x
            status_anchor_width = col2_label_width if col2 else col1_label_width
            right_col = (
                status_anchor_x
                + status_anchor_width
                + MENU_ITEM_PREFIX_WIDTH
                + MENU_RIGHT_COL_BUFFER
            )

            # Claude-Nutzungsstatistik-Spalte ganz rechts, an Terminalbreite verankert
            usage_col_x = width - USAGE_STATS_COL_WIDTH
            show_usage_col = (
                usage_stats_text is not None
                and usage_col_x < width
                and usage_col_x - right_col >= USAGE_STATS_MIN_GAP
            )

            # Titel links, Versionsnummer rechts
            stdscr.addstr(
                MENU_TITLE_ROW,
                UI_PADDING_X,
                banner_text,
                curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
            )
            version_x = width - len(version_text) - UI_PADDING_X
            if version_x > len(banner_text) + 4:
                stdscr.addstr(MENU_TITLE_ROW, version_x, version_text)

            # Separator
            sep = "─" * (width - 4)
            stdscr.addstr(
                MENU_SEPARATOR_ROW,
                UI_PADDING_X,
                sep,
                curses.color_pair(COLOR_PAIR_ORANGE),
            )

            # Menü (zwei Spalten links)
            _render_menu_column(stdscr, col1, current, col1_x, height)
            if col2_x < width:
                _render_menu_column(stdscr, col2, current, col2_x, height)

            # Status-Info (rechts, neben den ersten Menü-Zeilen)
            status_right_boundary = (
                usage_col_x - MENU_COLUMN_GAP_X
                if show_usage_col
                else width - UI_PADDING_X
            )
            for i, line in enumerate(info_lines):
                y = MENU_START_ROW + i
                if y >= height - 2 or right_col >= width:
                    break
                max_len = status_right_boundary - right_col
                stdscr.addstr(
                    y, right_col, line[:max_len], curses.color_pair(COLOR_PAIR_GRAY)
                )

            # Claude-Nutzungsstatistik (rechts außen, openusage-CLI)
            if show_usage_col and usage_stats_text is not None:
                for i, line in enumerate(usage_stats_text.split("\n")):
                    y = MENU_START_ROW + i
                    if y >= height - 2:
                        break
                    max_len = width - usage_col_x - UI_PADDING_X
                    stdscr.addstr(
                        y,
                        usage_col_x,
                        line.strip()[:max_len],
                        curses.color_pair(COLOR_PAIR_GREEN),
                    )

            # Footer (unterste Zeile, kein Rahmen)
            if height > 3:
                max_footer = width - 4
                stdscr.addstr(
                    height - 2,
                    UI_PADDING_X,
                    footer[:max_footer],
                    curses.color_pair(COLOR_PAIR_GRAY),
                )

            stdscr.refresh()

            key = stdscr.getch()

            if key == -1:
                if (
                    idle_refresh_predicate is None
                    or idle_refresh_predicate() != initial_predicate_state
                ):
                    return "__idle_refresh__"
                continue
            elif _is_up_key(key):
                current = (current - 1) % len(menu_items)
            elif _is_down_key(key):
                current = (current + 1) % len(menu_items)
            elif _is_left_key(key) or _is_right_key(key):
                current = _swap_menu_column(current, col1, col2)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _menu_item_at_position(
                    col1,
                    col2,
                    col1_x,
                    col2_x,
                    col1_label_width,
                    col2_label_width,
                    mouse_y,
                    mouse_x,
                    height,
                )
                if hit is None:
                    continue
                current = hit
                if bstate & curses.BUTTON1_CLICKED:
                    return menu_items[current][0]
            elif key == ord("\n") or key == KEY_SPACE:
                return menu_items[current][0]
            elif key == ord("q"):
                return None
            elif key == ord("r"):
                return "__refresh__"
            elif key == ord("x"):
                return "__toggle_ask_reset__"
            elif key == ord("o"):
                return "__toggle_overwrite_ask__"
            elif key == ord("h"):
                if idle_timeout_ms is not None:
                    stdscr.timeout(-1)
                _render_cheatsheet(stdscr, height, width)
                stdscr.getch()
                if idle_timeout_ms is not None:
                    stdscr.timeout(idle_timeout_ms)
                continue
            elif key == ord("s"):
                return "start"
            elif key == ord("t"):
                return "shell"
            elif key == ord("p"):
                return "plan"
            elif key == ord("e"):
                return "export_first"
            elif key == ord("i"):
                return "import_first"
            elif key == ord("v"):
                return "open_import_source"
    finally:
        if mouse_enabled:
            _disable_mouse_tracking()


def curses_confirm(
    stdscr: "curses.window",
    message: str,
    default: bool = False,
    mouse_enabled: bool = True,
) -> bool:
    """Ja/Nein-Dialog; ESC zählt als Nein."""
    _init_curses_colors(stdscr)
    if mouse_enabled:
        _enable_mouse_tracking()
    current = 0 if default else 1
    choices = ["Ja", "Nein"]

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            # Message (mehrzeilig und zentriert)
            lines = message.split("\n")
            start_y = height // 2 - len(lines) - 2

            for i, line in enumerate(lines):
                x = max(0, (width - len(line)) // 2)
                stdscr.addstr(
                    start_y + i,
                    x,
                    line,
                    curses.color_pair(COLOR_PAIR_GRAY) | curses.A_BOLD,
                )

            # Choices (Geometrie identisch zu _confirm_choice_at_position(): Präfix-
            # Breite + Label je Choice, "  " als Trenner zwischen den Choices).
            y = start_y + len(lines) + 2
            plain_line = "  ".join(
                [f"> {c}" if i == current else f"  {c}" for i, c in enumerate(choices)]
            )
            choice_x = (width - len(plain_line)) // 2
            x = choice_x
            for i, choice in enumerate(choices):
                is_current = i == current
                label = f"> {choice}" if is_current else f"  {choice}"
                attr = (
                    curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD
                    if is_current
                    else curses.A_NORMAL
                )
                stdscr.addstr(y, x, label, attr)
                x += MENU_ITEM_PREFIX_WIDTH + len(choice) + 2

            stdscr.refresh()

            key = stdscr.getch()

            if key == curses.KEY_LEFT:
                current = 0
            elif key == curses.KEY_RIGHT:
                current = 1
            elif key == KEY_TAB:
                current ^= 1  # Toggle zwischen Ja (0) und Nein (1)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _confirm_choice_at_position(
                    choices, choice_x, y, mouse_y, mouse_x
                )
                if hit is None:
                    continue
                current = hit
                if bstate & curses.BUTTON1_CLICKED:
                    return current == 0
            elif key == ord("\n") or key == KEY_SPACE:
                return current == 0
            elif key == ord("y") or key == ord("j"):  # j=ja (Deutsch), y=yes (Englisch)
                return True
            elif key == ord("n"):
                return False
            elif key == KEY_ESC:
                return False
    finally:
        if mouse_enabled:
            _disable_mouse_tracking()


def curses_input(
    stdscr: "curses.window",
    prompt: str,
    default: str = "",
) -> str | None:
    """Text-Eingabe mit Cursor-Support; None bei Abbruch (ESC)."""
    _init_curses_colors(stdscr)  # setzt curs_set(0), danach überschreiben
    curses.curs_set(1)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    y = height // 2
    stdscr.addstr(
        y - 2,
        UI_PADDING_X,
        prompt,
        curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
    )
    stdscr.addstr(y, UI_PADDING_X, "> ")

    user_input = default
    cursor_pos = len(user_input)

    while True:
        stdscr.addstr(
            y, ITEM_INDENT_X, user_input + " " * (width - len(user_input) - 6)
        )
        stdscr.move(y, ITEM_INDENT_X + cursor_pos)
        stdscr.refresh()

        key = stdscr.getch()

        if key == ord("\n"):
            return user_input
        elif key == KEY_ESC:
            return None
        elif key == curses.KEY_BACKSPACE or key == KEY_BACKSPACE_DEL:
            if cursor_pos > 0:
                user_input = user_input[: cursor_pos - 1] + user_input[cursor_pos:]
                cursor_pos -= 1
        elif key == curses.KEY_LEFT:
            cursor_pos = max(0, cursor_pos - 1)
        elif key == curses.KEY_RIGHT:
            cursor_pos = min(len(user_input), cursor_pos + 1)
        elif KEY_SPACE <= key <= KEY_PRINTABLE_MAX:
            user_input = user_input[:cursor_pos] + chr(key) + user_input[cursor_pos:]
            cursor_pos += 1


@overload
def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int,
    allow_edit: Literal[True],
    mouse_enabled: bool = True,
) -> tuple[str | None, bool]: ...


@overload
def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int = ...,
    allow_edit: Literal[False] = ...,
    mouse_enabled: bool = True,
) -> str | None: ...


def curses_select(
    stdscr: "curses.window",
    title: str,
    items: list[tuple[str, str]],
    default_index: int = 0,
    allow_edit: bool = False,
    mouse_enabled: bool = True,
) -> tuple[str | None, bool] | str | None:
    """Auswahl-Dialog für Listen (z. B. History).

    allow_edit=True: Tab öffnet einen Editierdialog, Rückgabe ist (value, edit_mode)
    statt nur value; (None, False) bei Abbruch statt nur None.
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        _enable_mouse_tracking()
    current = default_index

    try:
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            stdscr.addstr(
                2,
                UI_PADDING_X,
                title,
                curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
            )

            # Items (Platz für Hint-Zeile am Ende lassen)
            for i, (_, label) in enumerate(items):
                y = MENU_START_ROW + i
                if y >= height - 3:
                    break
                if i == current:
                    stdscr.addstr(
                        y,
                        ITEM_INDENT_X,
                        f"> {label}",
                        curses.color_pair(COLOR_PAIR_YELLOW) | curses.A_BOLD,
                    )
                else:
                    stdscr.addstr(y, ITEM_INDENT_X, f"  {label}")

            # Hint-Zeile
            if allow_edit:
                hint = "[Enter] Auswählen  [Tab] Bearbeiten  [ESC] Abbrechen"
            else:
                hint = "[Enter] Auswählen  [ESC] Abbrechen"
            stdscr.addstr(
                height - 2, UI_PADDING_X, hint, curses.color_pair(COLOR_PAIR_GRAY)
            )

            stdscr.refresh()

            key = stdscr.getch()

            if _is_up_key(key):
                current = (current - 1) % len(items)
            elif _is_down_key(key, include_tab=not allow_edit):
                current = (current + 1) % len(items)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _select_item_at_position(items, mouse_y, mouse_x, height)
                if hit is None:
                    continue
                current = hit
                if bstate & curses.BUTTON1_CLICKED:
                    if allow_edit:
                        return (items[current][0], False)
                    return items[current][0]
            elif (
                allow_edit and key == KEY_TAB
            ):  # Tab im Edit-Modus → Editierdialog öffnen
                return (items[current][0], True)
            elif key == ord("\n"):
                if allow_edit:
                    return (items[current][0], False)
                return items[current][0]
            elif key == KEY_ESC or key == ord("q"):
                if allow_edit:
                    return (None, False)
                return None
    finally:
        if mouse_enabled:
            _disable_mouse_tracking()


def curses_browse(
    stdscr: "curses.window",
    title: str,
    summary: str,
    items: list[tuple[str, str]],
    mouse_enabled: bool = True,
) -> None:
    """Scrollbare, mehrspaltige (`ls`-artige) Read-Only-Dateiliste.

    `Enter`/Klick kopiert den Basename des markierten Eintrags in die Zwischenablage,
    die Ansicht bleibt dabei offen (Inline-Bestätigung im Hint).
    """
    _init_curses_colors(stdscr)
    if mouse_enabled:
        _enable_mouse_tracking()

    try:
        height, width = stdscr.getmaxyx()

        # Guard-Clause für zu kleine Terminals
        if height < 8 or width < 40:
            stdscr.addstr(0, 0, "Terminal zu klein!")
            stdscr.getch()
            return

        current = 0

        if not items:
            stdscr.addstr(
                2,
                UI_PADDING_X,
                title,
                curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
            )
            stdscr.addstr(MENU_START_ROW, ITEM_INDENT_X, "Keine Dateien vorhanden.")
            stdscr.addstr(
                height - 2,
                UI_PADDING_X,
                "ESC Zurück",
                curses.color_pair(COLOR_PAIR_GRAY),
            )
            stdscr.refresh()
            while True:
                if stdscr.getch() == KEY_ESC:
                    return

        status_message: str | None = None

        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            # Verfügbare Zeilen: Header(3) + Summary(1) + Leerzeile(1) oben, Hint(2) unten
            viewport_height = height - 7

            stdscr.addstr(
                1,
                UI_PADDING_X,
                title,
                curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
            )
            stdscr.addstr(2, UI_PADDING_X, summary, curses.color_pair(COLOR_PAIR_GRAY))

            # Spaltenlayout und Scroll-Offset berechnen (zeilenbasiert innerhalb der Spalte)
            num_columns, column_width, rows = _compute_browse_column_layout(
                items, width
            )
            current_row = current % rows
            scroll_offset = (
                max(0, current_row - viewport_height + 1)
                if current_row >= viewport_height
                else 0
            )

            # Dateiliste spaltenweise rendern
            list_start_y = 4
            _render_browse_columns(
                stdscr,
                items,
                current,
                scroll_offset,
                num_columns,
                column_width,
                rows,
                list_start_y,
                viewport_height,
                height,
            )

            # Position-Indikator und Hint
            pos_text = f"[{current + 1}/{len(items)}]"
            hint = (
                status_message
                if status_message is not None
                else "↑↓ Navigieren  ←→ Spalte wechseln | ESC Zurück"
            )
            stdscr.addstr(
                height - 2, UI_PADDING_X, hint, curses.color_pair(COLOR_PAIR_GRAY)
            )
            stdscr.addstr(
                height - 2,
                width - len(pos_text) - UI_PADDING_X,
                pos_text,
                curses.color_pair(COLOR_PAIR_GRAY),
            )

            stdscr.refresh()

            key = stdscr.getch()
            status_message = None

            if _is_up_key(key):
                current = (current - 1) % len(items)
            elif _is_down_key(key):
                current = (current + 1) % len(items)
            elif _is_left_key(key):
                current = max(0, current - rows)
            elif _is_right_key(key):
                current = min(len(items) - 1, current + rows)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mouse_x, mouse_y, _, bstate = curses.getmouse()
                except curses.error:
                    continue
                hit = _browse_grid_item_at_position(
                    items,
                    num_columns,
                    column_width,
                    rows,
                    scroll_offset,
                    list_start_y,
                    viewport_height,
                    mouse_y,
                    mouse_x,
                    height,
                )
                if hit is not None:
                    current = hit
                    if bstate & curses.BUTTON1_CLICKED:
                        filename = os.path.basename(items[current][0])
                        status_message = (
                            f"✔ Kopiert: {filename}"
                            if _copy_to_clipboard(filename)
                            else "⚠ Kopieren fehlgeschlagen"
                        )
            elif key == ord("\n"):
                filename = os.path.basename(items[current][0])
                status_message = (
                    f"✔ Kopiert: {filename}"
                    if _copy_to_clipboard(filename)
                    else "⚠ Kopieren fehlgeschlagen"
                )
            elif key == KEY_ESC:
                return
    finally:
        if mouse_enabled:
            _disable_mouse_tracking()


def curses_message(
    stdscr: "curses.window",
    title: str,
    message: str,
) -> None:
    """Zeigt eine Meldung und wartet auf einen beliebigen Tastendruck."""
    _init_curses_colors(stdscr)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    y = height // 2 - 3
    stdscr.addstr(
        y,
        max(0, (width - len(title)) // 2),
        title,
        curses.color_pair(COLOR_PAIR_ORANGE) | curses.A_BOLD,
    )

    lines = message.split("\n")
    for i, line in enumerate(lines):
        stdscr.addstr(
            y + 2 + i,
            max(0, (width - len(line)) // 2),
            line,
            curses.color_pair(COLOR_PAIR_GRAY),
        )

    hint = "[ Beliebige Taste drücken ]"
    stdscr.addstr(y + 2 + len(lines) + 1, max(0, (width - len(hint)) // 2), hint)
    stdscr.refresh()
    stdscr.getch()
