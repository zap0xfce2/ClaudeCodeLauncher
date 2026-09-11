from pathlib import Path

import pytest

from claude_code_launcher.config_manager import ConfigManager
from claude_code_launcher.toml_io import _dump_toml


def test_config_manager_creates_default_config_when_missing(tmp_path):
    config_path = tmp_path / "config.toml"
    ConfigManager(config_path)
    assert config_path.exists()


def test_config_manager_load_config_merges_missing_default_keys(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(_dump_toml({"history": [], "max_history_entries": 5}))
    manager = ConfigManager(config_path)
    assert (manager.config["max_history_entries"], manager.config["ask_for_reset"]) == (5, True)


def test_config_manager_load_config_backs_up_corrupt_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("= invalid toml")
    ConfigManager(config_path)
    assert (tmp_path / "config.toml.bak").exists()


def test_config_manager_save_and_reload_persists_changes(tmp_path):
    config_path = tmp_path / "config.toml"
    manager = ConfigManager(config_path)
    manager.config["claude_instruction"] = "Sag Hallo"
    manager.save_config()
    reloaded = ConfigManager(config_path)
    assert reloaded.config["claude_instruction"] == "Sag Hallo"


def test_toggle_bool_option_negates_and_persists(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.toggle_bool_option("ask_for_reset")
    assert manager.config["ask_for_reset"] is False


def test_record_shortcut_usage_deduplicates_and_moves_to_front(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.record_shortcut_usage("r")
    manager.record_shortcut_usage("s")
    manager.record_shortcut_usage("r")
    assert manager.config["recent_shortcuts"] == ["r", "s"]


def test_record_shortcut_usage_caps_at_max_entries(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    for letter in "abcdefg":
        manager.record_shortcut_usage(letter)
    assert manager.config["recent_shortcuts"] == ["g", "f", "e", "d", "c", "b"]


def test_add_to_history_deduplicates_same_path_and_type(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.add_to_history(Path("/workspace/a"), "export")
    manager.add_to_history(Path("/workspace/a"), "export")
    assert len(manager.config["history"]) == 1


def test_add_to_history_stores_remote_path_unchanged(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.add_to_history("user@host:/backup", "export")
    assert manager.config["history"][0]["path"] == "user@host:/backup"


def test_add_to_history_synthetic_sets_flag(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.add_to_history(Path("/workspace/a"), "export", synthetic=True)
    assert manager.config["history"][0]["synthetic"] is True


def test_add_to_history_without_synthetic_omits_flag(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.add_to_history(Path("/workspace/a"), "export")
    assert "synthetic" not in manager.config["history"][0]


def test_add_to_history_real_export_replaces_synthetic_entry(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.add_to_history(Path("/workspace/a"), "export", synthetic=True)
    manager.add_to_history(Path("/workspace/a"), "export")
    assert len(manager.config["history"]) == 1
    assert "synthetic" not in manager.config["history"][0]


def test_add_to_history_raises_on_invalid_type(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    with pytest.raises(ValueError):
        manager.add_to_history(Path("/workspace/a"), "sync")


def test_add_to_history_caps_at_max_history_entries(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.config["max_history_entries"] = 3
    manager.save_config()
    for i in range(5):
        manager.add_to_history(Path(f"/workspace/{i}"), "export")
    assert len(manager.config["history"]) == 3


def test_get_history_filters_by_type_and_includes_legacy_entries_without_type(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        _dump_toml(
            {
                "history": [
                    {"path": "/a", "type": "export"},
                    {"path": "/b", "type": "import"},
                    {"path": "/c"},
                ]
            }
        )
    )
    manager = ConfigManager(config_path)
    export_paths = {h["path"] for h in manager.get_history("export")}
    assert export_paths == {"/a", "/c"}


def test_get_history_raises_on_invalid_type(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    with pytest.raises(ValueError):
        manager.get_history("sync")


def test_record_reset_sets_last_reset_timestamp(tmp_path):
    manager = ConfigManager(tmp_path / "config.toml")
    manager.record_reset()
    assert "last_reset_timestamp" in manager.config
