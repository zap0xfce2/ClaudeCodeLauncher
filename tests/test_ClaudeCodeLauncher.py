import curses
import time
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ClaudeCodeLauncher as ccl


# --- _resolve_xterm256_color ---


def test_resolve_xterm256_color_returns_xterm_value_on_256_color_terminal(monkeypatch):
    monkeypatch.setattr(curses, "COLORS", 256, raising=False)
    assert ccl._resolve_xterm256_color(166, curses.COLOR_YELLOW) == 166


def test_resolve_xterm256_color_returns_fallback_below_256_colors(monkeypatch):
    monkeypatch.setattr(curses, "COLORS", 8, raising=False)
    assert ccl._resolve_xterm256_color(166, curses.COLOR_YELLOW) == curses.COLOR_YELLOW


# --- Navigations-Tasten ---


@pytest.mark.parametrize("key", [curses.KEY_UP, curses.KEY_BTAB])
def test_is_up_key_true_for_up_and_shift_tab(key):
    assert ccl._is_up_key(key) is True


def test_is_up_key_false_for_other_key():
    assert ccl._is_up_key(curses.KEY_DOWN) is False


def test_is_down_key_true_for_down():
    assert ccl._is_down_key(curses.KEY_DOWN) is True


def test_is_down_key_tab_respects_include_tab_flag():
    assert ccl._is_down_key(ccl.KEY_TAB, include_tab=False) is False


def test_is_left_key_true_for_left():
    assert ccl._is_left_key(curses.KEY_LEFT) is True


def test_is_left_key_false_for_right():
    assert ccl._is_left_key(curses.KEY_RIGHT) is False


def test_is_right_key_true_for_right():
    assert ccl._is_right_key(curses.KEY_RIGHT) is True


def test_is_right_key_false_for_left():
    assert ccl._is_right_key(curses.KEY_LEFT) is False


# --- _split_menu_columns / _swap_menu_column ---


def test_split_menu_columns_assigns_workflow_and_utility_actions():
    menu_items = [("plan", "P"), ("browse", "B"), ("start", "S"), ("shell", "T")]
    col1, col2 = ccl._split_menu_columns(menu_items)
    assert (col1, col2) == ([(0, "P"), (2, "S")], [(1, "B"), (3, "T")])


def test_split_menu_columns_empty_input_returns_empty_columns():
    assert ccl._split_menu_columns([]) == ([], [])


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
    assert ccl._swap_menu_column(current, col1, col2) == expected


def test_swap_menu_column_returns_unchanged_when_target_column_empty():
    assert ccl._swap_menu_column(0, [(0, "a")], []) == 0


# --- _menu_column_hit_index / _menu_item_at_position ---


def test_menu_column_hit_index_hits_first_row():
    column = [(0, "Plan"), (1, "Start")]
    hit = ccl._menu_column_hit_index(column, x=2, label_width=5, mouse_y=4, mouse_x=5, height=20)
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
    hit = ccl._menu_column_hit_index(
        column, x=2, label_width=5, mouse_y=mouse_y, mouse_x=mouse_x, height=height
    )
    assert hit is None


def test_menu_item_at_position_hits_second_column():
    hit = ccl._menu_item_at_position(
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
    hit = ccl._menu_item_at_position(
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
    assert ccl._compute_browse_column_layout([], width=80) == (1, 6, 0)


def test_compute_browse_column_layout_multi_column():
    items = [(str(i), "abc") for i in range(5)]
    assert ccl._compute_browse_column_layout(items, width=100) == (5, 9, 1)


def test_compute_browse_column_layout_falls_back_to_single_column_when_narrow():
    items = [(str(i), "abc") for i in range(5)]
    num_columns, _column_width, rows = ccl._compute_browse_column_layout(items, width=10)
    assert (num_columns, rows) == (1, 5)


# --- _browse_grid_item_at_position ---


def test_browse_grid_item_at_position_hits_second_column_second_row():
    items = [(str(i), "label") for i in range(5)]
    idx = ccl._browse_grid_item_at_position(
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
    idx = ccl._browse_grid_item_at_position(
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
    hit = ccl._confirm_choice_at_position(["Ja", "Nein"], choice_x=2, y=10, mouse_y=10, mouse_x=3)
    assert hit == 0


def test_confirm_choice_at_position_hits_nein():
    hit = ccl._confirm_choice_at_position(["Ja", "Nein"], choice_x=2, y=10, mouse_y=10, mouse_x=9)
    assert hit == 1


@pytest.mark.parametrize(
    ("mouse_y", "mouse_x"),
    [
        (11, 3),  # falsche Zeile
        (10, 6),  # Lücke zwischen den Choices
    ],
)
def test_confirm_choice_at_position_misses(mouse_y, mouse_x):
    hit = ccl._confirm_choice_at_position(
        ["Ja", "Nein"], choice_x=2, y=10, mouse_y=mouse_y, mouse_x=mouse_x
    )
    assert hit is None


# --- _format_relative_reset / _format_absolute_time ---


def test_format_relative_reset_days_and_hours():
    reset_iso = (datetime.now(timezone.utc) + timedelta(days=4, hours=23, minutes=30)).isoformat()
    assert ccl._format_relative_reset(reset_iso) == "4d23h"


def test_format_relative_reset_already_expired_returns_zero_minutes():
    reset_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert ccl._format_relative_reset(reset_iso) == "0m"


def test_format_absolute_time_formats_as_local_hh_mm(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    assert ccl._format_absolute_time("2024-01-01T12:34:00Z") == "12:34"


# --- usage_cache Konvertierung ---


def test_usage_stats_to_cache_and_back_roundtrip():
    usage = {
        "session": {"used": 0.27, "resetsAt": "2026-08-12T00:00:00Z"},
        "weekly": {"used": 0.11, "resetsAt": "2026-08-15T00:00:00Z"},
        "generated_at": "2026-08-11T10:00:00Z",
        "expires_at": "2026-08-11T10:05:00Z",
    }
    assert ccl._usage_stats_from_cache(ccl._usage_stats_to_cache(usage)) == usage


# --- TOML-Serialisierung ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        (42, "42"),
        (1.5, "1.5"),
        ("bar", '"bar"'),
        ([], "[]"),
        ([".git", "*.pyc"], '[".git", "*.pyc"]'),
    ],
)
def test_toml_scalar(value, expected):
    assert ccl._toml_scalar(value) == expected


def test_toml_scalar_raises_type_error_for_unsupported_type():
    with pytest.raises(TypeError):
        ccl._toml_scalar({"unsupported": "dict"})


def test_toml_table_block_builds_header_and_key_value_lines():
    assert ccl._toml_table_block("claude_env", {"FOO": "bar"}) == '[claude_env]\nFOO = "bar"'


def test_toml_array_of_tables_block_builds_repeated_blocks():
    entries = [{"path": "/a", "type": "export"}, {"path": "/b", "type": "import"}]
    expected = '[[history]]\npath = "/a"\ntype = "export"\n\n[[history]]\npath = "/b"\ntype = "import"'
    assert ccl._toml_array_of_tables_block("history", entries) == expected


def test_dump_toml_roundtrips_through_tomllib():
    data = {
        "max_history_entries": 10,
        "ask_for_reset": True,
        "export_ignore_patterns": [".git", "*.pyc"],
        "claude_env": {"FOO": "bar"},
        "history": [{"path": "/a", "type": "export"}, {"path": "/b", "type": "import"}],
    }
    assert tomllib.loads(ccl._dump_toml(data)) == data


# --- ConfigManager ---


def test_config_manager_creates_default_config_when_missing(tmp_path):
    config_path = tmp_path / "config.toml"
    ccl.ConfigManager(config_path)
    assert config_path.exists()


def test_config_manager_load_config_merges_missing_default_keys(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(ccl._dump_toml({"history": [], "max_history_entries": 5}))
    manager = ccl.ConfigManager(config_path)
    assert (manager.config["max_history_entries"], manager.config["ask_for_reset"]) == (5, True)


def test_config_manager_load_config_backs_up_corrupt_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("= invalid toml")
    ccl.ConfigManager(config_path)
    assert (tmp_path / "config.toml.bak").exists()


def test_config_manager_save_and_reload_persists_changes(tmp_path):
    config_path = tmp_path / "config.toml"
    manager = ccl.ConfigManager(config_path)
    manager.config["claude_instruction"] = "Sag Hallo"
    manager.save_config()
    reloaded = ccl.ConfigManager(config_path)
    assert reloaded.config["claude_instruction"] == "Sag Hallo"


def test_toggle_bool_option_negates_and_persists(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    manager.toggle_bool_option("ask_for_reset")
    assert manager.config["ask_for_reset"] is False


def test_record_shortcut_usage_deduplicates_and_moves_to_front(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    manager.record_shortcut_usage("r")
    manager.record_shortcut_usage("s")
    manager.record_shortcut_usage("r")
    assert manager.config["recent_shortcuts"] == ["r", "s"]


def test_record_shortcut_usage_caps_at_max_entries(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    for letter in "abcdefg":
        manager.record_shortcut_usage(letter)
    assert manager.config["recent_shortcuts"] == ["g", "f", "e", "d", "c", "b"]


def test_add_to_history_deduplicates_same_path_and_type(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    manager.add_to_history(Path("/workspace/a"), "export")
    manager.add_to_history(Path("/workspace/a"), "export")
    assert len(manager.config["history"]) == 1


def test_add_to_history_raises_on_invalid_type(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    with pytest.raises(ValueError):
        manager.add_to_history(Path("/workspace/a"), "sync")


def test_add_to_history_caps_at_max_history_entries(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    manager.config["max_history_entries"] = 3
    manager.save_config()
    for i in range(5):
        manager.add_to_history(Path(f"/workspace/{i}"), "export")
    assert len(manager.config["history"]) == 3


def test_get_history_filters_by_type_and_includes_legacy_entries_without_type(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        ccl._dump_toml(
            {
                "history": [
                    {"path": "/a", "type": "export"},
                    {"path": "/b", "type": "import"},
                    {"path": "/c"},
                ]
            }
        )
    )
    manager = ccl.ConfigManager(config_path)
    export_paths = {h["path"] for h in manager.get_history("export")}
    assert export_paths == {"/a", "/c"}


def test_get_history_raises_on_invalid_type(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    with pytest.raises(ValueError):
        manager.get_history("sync")


def test_record_reset_sets_last_reset_timestamp(tmp_path):
    manager = ccl.ConfigManager(tmp_path / "config.toml")
    manager.record_reset()
    assert "last_reset_timestamp" in manager.config


# --- WorkspaceManager ---


def test_get_exclude_args_without_config_manager_returns_empty_list(tmp_path):
    manager = ccl.WorkspaceManager(tmp_path)
    assert manager._get_exclude_args("export_ignore_patterns") == []


def test_get_exclude_args_builds_rsync_exclude_flags(tmp_path):
    config_manager = ccl.ConfigManager(tmp_path / "config.toml")
    config_manager.config["export_ignore_patterns"] = [".git", "*.pyc"]
    manager = ccl.WorkspaceManager(tmp_path, config_manager)
    exclude_args = manager._get_exclude_args("export_ignore_patterns")
    assert exclude_args == ["--exclude=.git", "--exclude=*.pyc"]


@pytest.mark.parametrize(
    ("filename", "patterns", "expected"),
    [
        (".git", [".git", "*.pyc"], ".git"),
        ("foo.pyc", [".git", "*.pyc"], "*.pyc"),
        ("foo.txt", [".git", "*.pyc"], None),
    ],
)
def test_is_file_ignored(filename, patterns, expected):
    assert ccl.WorkspaceManager._is_file_ignored(filename, patterns) == expected


def test_build_content_entry_for_small_file(tmp_path):
    file_path = tmp_path / "foo.txt"
    file_path.write_text("hi")
    manager = ccl.WorkspaceManager(tmp_path)
    rel_path, label, _mtime = manager._build_content_entry(file_path)
    assert (rel_path, label) == ("foo.txt", "📄 foo.txt  (2 B)")


def test_build_content_entry_for_dot_folder_sums_nested_file_sizes(tmp_path):
    folder = tmp_path / ".git"
    folder.mkdir()
    (folder / "a").write_text("x" * 10)
    (folder / "b").write_text("x" * 5)
    manager = ccl.WorkspaceManager(tmp_path)
    rel_path, label, _mtime = manager._build_content_entry(folder)
    assert (rel_path, label) == (".git", "📁 .git  (15 B)")
