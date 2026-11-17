from claude_code_launcher.launcher_app import LauncherApp

RESET_TS = "2026-11-11T12:00:00"
ENTRY_BEFORE_RESET = {"timestamp": "2026-11-11T11:00:00", "path": "/tmp/projekt"}
ENTRY_AFTER_RESET = {"timestamp": "2026-11-11T13:00:00", "path": "/tmp/projekt"}


def test_history_line_hidden_when_older_than_reset() -> None:
    assert LauncherApp._get_history_line("Import", ENTRY_BEFORE_RESET, RESET_TS) == ""


def test_history_line_shown_when_newer_than_reset() -> None:
    expected = "   Letzter Import: 11.11.2026 13:00 (projekt)\n"
    assert LauncherApp._get_history_line("Import", ENTRY_AFTER_RESET, RESET_TS) == expected


def test_history_line_shown_without_reset() -> None:
    expected = "   Letzter Export: 11.11.2026 11:00 (projekt)\n"
    assert LauncherApp._get_history_line("Export", ENTRY_BEFORE_RESET, None) == expected


def test_reset_since_true_when_reset_after_entry() -> None:
    assert LauncherApp._reset_since(ENTRY_BEFORE_RESET, RESET_TS) is True


def test_reset_since_false_when_entry_after_reset() -> None:
    assert LauncherApp._reset_since(ENTRY_AFTER_RESET, RESET_TS) is False


def test_reset_since_false_without_reset() -> None:
    assert LauncherApp._reset_since(ENTRY_BEFORE_RESET, None) is False


def test_reset_since_true_without_entry_but_with_reset() -> None:
    assert LauncherApp._reset_since(None, RESET_TS) is True
