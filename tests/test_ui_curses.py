import curses

import pytest

from claude_code_launcher import ui_curses
from claude_code_launcher.constants import KEY_TAB


# --- _resolve_xterm256_color ---


def test_resolve_xterm256_color_returns_xterm_value_on_256_color_terminal(monkeypatch):
    monkeypatch.setattr(curses, "COLORS", 256, raising=False)
    assert ui_curses._resolve_xterm256_color(166, curses.COLOR_YELLOW) == 166


def test_resolve_xterm256_color_returns_fallback_below_256_colors(monkeypatch):
    monkeypatch.setattr(curses, "COLORS", 8, raising=False)
    assert ui_curses._resolve_xterm256_color(166, curses.COLOR_YELLOW) == curses.COLOR_YELLOW


# --- Navigations-Tasten ---


@pytest.mark.parametrize("key", [curses.KEY_UP, curses.KEY_BTAB])
def test_is_up_key_true_for_up_and_shift_tab(key):
    assert ui_curses._is_up_key(key) is True


def test_is_up_key_false_for_other_key():
    assert ui_curses._is_up_key(curses.KEY_DOWN) is False


def test_is_down_key_true_for_down():
    assert ui_curses._is_down_key(curses.KEY_DOWN) is True


def test_is_down_key_tab_respects_include_tab_flag():
    assert ui_curses._is_down_key(KEY_TAB, include_tab=False) is False


def test_is_left_key_true_for_left():
    assert ui_curses._is_left_key(curses.KEY_LEFT) is True


def test_is_left_key_false_for_right():
    assert ui_curses._is_left_key(curses.KEY_RIGHT) is False


def test_is_right_key_true_for_right():
    assert ui_curses._is_right_key(curses.KEY_RIGHT) is True


def test_is_right_key_false_for_left():
    assert ui_curses._is_right_key(curses.KEY_LEFT) is False


# --- _split_menu_columns / _swap_menu_column ---


def test_split_menu_columns_assigns_workflow_and_utility_actions():
    menu_items = [("plan", "P"), ("browse", "B"), ("start", "S"), ("shell", "T")]
    col1, col2 = ui_curses._split_menu_columns(menu_items)
    assert (col1, col2) == ([(0, "P"), (2, "S")], [(1, "B"), (3, "T")])


def test_split_menu_columns_empty_input_returns_empty_columns():
    assert ui_curses._split_menu_columns([]) == ([], [])


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (0, 1),  # col1 Zeile 0 -> col2 Zeile 0
        (4, 3),  # col1 Zeile 2 -> col2 geklemmt auf letzte Zeile (1)
        (1, 0),  # col2 Zeile 0 -> col1 Zeile 0
        (99, 99),  # nicht vorhanden -> unverändert
    ],
)
def test_swap_menu_column(current, expected):
    col1 = [(0, "a"), (2, "b"), (4, "c")]
    col2 = [(1, "x"), (3, "y")]
    assert ui_curses._swap_menu_column(current, col1, col2) == expected


def test_swap_menu_column_returns_unchanged_when_target_column_empty():
    assert ui_curses._swap_menu_column(0, [(0, "a")], []) == 0


# --- _menu_column_hit_index / _menu_item_at_position ---


def test_menu_column_hit_index_hits_first_row():
    column = [(0, "Plan"), (1, "Start")]
    hit = ui_curses._menu_column_hit_index(column, x=2, label_width=5, mouse_y=4, mouse_x=5, height=20)
    assert hit == 0


@pytest.mark.parametrize(
    ("mouse_y", "mouse_x", "height"),
    [
        (3, 5, 20),  # Zeile negativ
        (6, 5, 20),  # Zeile außerhalb der Spalte
        (4, 10, 20),  # x außerhalb des Labels
        (4, 5, 6),  # außerhalb der Sichtbarkeitsgrenze
    ],
)
def test_menu_column_hit_index_misses(mouse_y, mouse_x, height):
    column = [(0, "Plan"), (1, "Start")]
    hit = ui_curses._menu_column_hit_index(
        column, x=2, label_width=5, mouse_y=mouse_y, mouse_x=mouse_x, height=height
    )
    assert hit is None


def test_menu_item_at_position_hits_second_column():
    hit = ui_curses._menu_item_at_position(
        [(0, "Plan")],
        [(1, "Start")],
        col1_x=2,
        col2_x=12,
        col1_label_width=4,
        col2_label_width=5,
        mouse_y=4,
        mouse_x=13,
        height=20,
    )
    assert hit == 1


def test_menu_item_at_position_miss_returns_none():
    hit = ui_curses._menu_item_at_position(
        [(0, "Plan")],
        [(1, "Start")],
        col1_x=2,
        col2_x=12,
        col1_label_width=4,
        col2_label_width=5,
        mouse_y=4,
        mouse_x=9,
        height=20,
    )
    assert hit is None


# --- _compute_browse_column_layout ---


def test_compute_browse_column_layout_empty_items():
    assert ui_curses._compute_browse_column_layout([], width=80) == (1, 6, 0)


def test_compute_browse_column_layout_multi_column():
    items = [(str(i), "abc") for i in range(5)]
    assert ui_curses._compute_browse_column_layout(items, width=100) == (5, 9, 1)


def test_compute_browse_column_layout_falls_back_to_single_column_when_narrow():
    items = [(str(i), "abc") for i in range(5)]
    num_columns, _column_width, rows = ui_curses._compute_browse_column_layout(items, width=10)
    assert (num_columns, rows) == (1, 5)


# --- _browse_grid_item_at_position ---


def test_browse_grid_item_at_position_hits_second_column_second_row():
    items = [(str(i), "label") for i in range(5)]
    idx = ui_curses._browse_grid_item_at_position(
        items,
        num_columns=2,
        column_width=10,
        rows=3,
        scroll_offset=0,
        list_start_y=6,
        viewport_height=3,
        mouse_y=7,
        mouse_x=12,
        height=30,
    )
    assert idx == 4


@pytest.mark.parametrize(
    ("mouse_y", "mouse_x"),
    [
        (9, 12),  # Zeile außerhalb des Viewports
        (6, 1),  # x links von UI_PADDING_X
        (6, 25),  # Spalte außerhalb num_columns
        (8, 12),  # letzte Grid-Zeile ohne Eintrag (nur 5 Items)
    ],
)
def test_browse_grid_item_at_position_misses(mouse_y, mouse_x):
    items = [(str(i), "label") for i in range(5)]
    idx = ui_curses._browse_grid_item_at_position(
        items,
        num_columns=2,
        column_width=10,
        rows=3,
        scroll_offset=0,
        list_start_y=6,
        viewport_height=3,
        mouse_y=mouse_y,
        mouse_x=mouse_x,
        height=30,
    )
    assert idx is None


# --- _confirm_choice_at_position ---


def test_confirm_choice_at_position_hits_ja():
    hit = ui_curses._confirm_choice_at_position(["Ja", "Nein"], choice_x=2, y=10, mouse_y=10, mouse_x=3)
    assert hit == 0


def test_confirm_choice_at_position_hits_nein():
    hit = ui_curses._confirm_choice_at_position(["Ja", "Nein"], choice_x=2, y=10, mouse_y=10, mouse_x=9)
    assert hit == 1


@pytest.mark.parametrize(
    ("mouse_y", "mouse_x"),
    [
        (11, 3),  # falsche Zeile
        (10, 6),  # Lücke zwischen den Choices
    ],
)
def test_confirm_choice_at_position_misses(mouse_y, mouse_x):
    hit = ui_curses._confirm_choice_at_position(
        ["Ja", "Nein"], choice_x=2, y=10, mouse_y=mouse_y, mouse_x=mouse_x
    )
    assert hit is None
