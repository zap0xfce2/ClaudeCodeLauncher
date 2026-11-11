import pytest

from claude_code_launcher.config_manager import ConfigManager
from claude_code_launcher.workspace_manager import (
    WorkspaceManager,
    _format_progress,
    _is_rsync_item_line,
)


def test_get_exclude_args_combines_base_and_specific_patterns(tmp_path):
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["ignore_patterns"] = [".env"]
    config_manager.config["export_ignore_patterns"] = [".git"]
    manager = WorkspaceManager(tmp_path, config_manager)
    exclude_args = manager._get_exclude_args("export_ignore_patterns")
    assert exclude_args == ["--exclude=.env", "--exclude=.git"]


@pytest.mark.parametrize(
    ("filename", "patterns", "expected"),
    [
        (".git", [".git", "*.pyc"], ".git"),
        ("foo.pyc", [".git", "*.pyc"], "*.pyc"),
        ("foo.txt", [".git", "*.pyc"], None),
    ],
)
def test_is_file_ignored(filename, patterns, expected):
    assert WorkspaceManager._is_file_ignored(filename, patterns) == expected


def test_get_ignore_patterns_without_config_manager_returns_empty_list(tmp_path):
    manager = WorkspaceManager(tmp_path)
    assert manager._get_ignore_patterns("export_ignore_patterns") == []


def test_get_ignore_patterns_without_extra_key_returns_base_only(tmp_path):
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["ignore_patterns"] = ["*.swp"]
    config_manager.config["export_ignore_patterns"] = [".git"]
    manager = WorkspaceManager(tmp_path, config_manager)
    assert manager._get_ignore_patterns() == ["*.swp"]


def test_get_ignore_patterns_combines_base_and_extra_key(tmp_path):
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["ignore_patterns"] = ["*.swp"]
    config_manager.config["import_ignore_patterns"] = [".git"]
    manager = WorkspaceManager(tmp_path, config_manager)
    result = manager._get_ignore_patterns("import_ignore_patterns")
    assert result == ["*.swp", ".git"]


def test_is_empty_true_for_nonexistent_workspace(tmp_path):
    manager = WorkspaceManager(tmp_path / "missing")
    assert manager.is_empty() is True


def test_is_empty_true_when_only_settings_local_json_present(tmp_path):
    (tmp_path / "settings.local.json").write_text("{}")
    manager = WorkspaceManager(tmp_path)
    assert manager.is_empty() is True


def test_is_empty_false_when_relevant_file_present(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("content")
    manager = WorkspaceManager(tmp_path)
    assert manager.is_empty() is False


def test_is_empty_true_when_only_ignored_file_present(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".Plan.md.swp").write_text("swap")
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["ignore_patterns"] = ["*.swp"]
    manager = WorkspaceManager(workspace, config_manager)
    assert manager.is_empty() is True


def test_is_empty_false_when_non_ignored_file_present_alongside_ignored_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".Plan.md.swp").write_text("swap")
    (workspace / "Plan.md").write_text("plan")
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["ignore_patterns"] = ["*.swp"]
    manager = WorkspaceManager(workspace, config_manager)
    assert manager.is_empty() is False


def test_get_status_excludes_ignored_files_from_count(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".Plan.md.swp").write_text("swap")
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["ignore_patterns"] = ["*.swp"]
    manager = WorkspaceManager(workspace, config_manager)
    assert manager.get_status()["is_empty"] is True


def test_build_content_entry_for_small_file(tmp_path):
    file_path = tmp_path / "foo.txt"
    file_path.write_text("hi")
    manager = WorkspaceManager(tmp_path)
    rel_path, label, _mtime = manager._build_content_entry(file_path)
    assert (rel_path, label) == ("foo.txt", "📄 foo.txt  (2 B)")


def test_build_content_entry_for_dot_folder_sums_nested_file_sizes(tmp_path):
    folder = tmp_path / ".git"
    folder.mkdir()
    (folder / "a").write_text("x" * 10)
    (folder / "b").write_text("x" * 5)
    manager = WorkspaceManager(tmp_path)
    rel_path, label, _mtime = manager._build_content_entry(folder)
    assert (rel_path, label) == (".git", "📁 .git  (15 B)")


# --- needs_overwrite_confirmation / matched_ignore_pattern ---


def test_needs_overwrite_confirmation_true_without_config_manager(tmp_path):
    manager = WorkspaceManager(tmp_path)
    assert manager.needs_overwrite_confirmation() is True


def test_needs_overwrite_confirmation_false_when_dont_ask_enabled(tmp_path):
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["dont_ask_on_export_overwrite"] = True
    manager = WorkspaceManager(tmp_path, config_manager)
    assert manager.needs_overwrite_confirmation() is False


def test_matched_ignore_pattern_returns_matching_pattern(tmp_path):
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["export_ignore_patterns"] = [".git"]
    manager = WorkspaceManager(tmp_path, config_manager)
    assert manager.matched_ignore_pattern(".git", "export_ignore_patterns") == ".git"


# --- export_to / export_file_to / import_file_from / import_from ---


def test_export_to_copies_files_and_returns_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("content")
    destination = tmp_path / "backup"
    manager = WorkspaceManager(workspace)

    manager.export_to(destination)

    assert (destination / "CLAUDE.md").read_text() == "content"


def test_export_to_returns_failure_when_rsync_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "claude_code_launcher.workspace_manager.RSYNC_BINARY", "does-not-exist-binary"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WorkspaceManager(workspace)

    result = manager.export_to(tmp_path / "backup")

    assert result.success is False


def test_export_file_to_copies_single_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("content")
    manager = WorkspaceManager(workspace)
    destination = tmp_path / "out.md"

    manager.export_file_to("CLAUDE.md", destination)

    assert destination.read_text() == "content"


def test_export_file_to_returns_failure_when_source_missing(tmp_path):
    manager = WorkspaceManager(tmp_path)

    result = manager.export_file_to("missing.md", tmp_path / "out.md")

    assert result.success is False


def test_import_file_from_copies_into_workspace_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_file = tmp_path / "CLAUDE.md"
    source_file.write_text("content")
    manager = WorkspaceManager(workspace)

    manager.import_file_from(source_file)

    assert (workspace / "CLAUDE.md").read_text() == "content"


def test_import_file_from_returns_failure_when_source_missing(tmp_path):
    manager = WorkspaceManager(tmp_path / "workspace")

    result = manager.import_file_from(tmp_path / "missing.md")

    assert result.success is False


def test_export_file_to_skips_parent_mkdir_for_remote_destination_string(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("content")
    manager = WorkspaceManager(workspace)
    recorded = {}
    monkeypatch.setattr(
        manager,
        "_rsync_copy_file",
        lambda source, destination: recorded.update(destination=destination),
    )

    manager.export_file_to("CLAUDE.md", "user@host:/remote/out.md")

    assert recorded["destination"] == "user@host:/remote/out.md"


def test_import_file_from_derives_filename_from_remote_source_path(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = WorkspaceManager(workspace)
    recorded = {}
    monkeypatch.setattr(
        manager,
        "_rsync_copy_file",
        lambda source, destination: recorded.update(destination=destination),
    )

    manager.import_file_from("user@host:/remote/dir/CLAUDE.md")

    assert recorded["destination"] == workspace / "CLAUDE.md"


def test_import_from_mirrors_source_into_workspace_and_deletes_excluded(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "CLAUDE.md").write_text("new content")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "stale.txt").write_text("old")
    manager = WorkspaceManager(workspace)

    manager.import_from(source)

    assert [p.name for p in workspace.iterdir()] == ["CLAUDE.md"]


# --- respect_gitignore ---


def test_import_from_respects_gitignore_in_source_excludes_listed_file(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".gitignore").write_text(".env\n")
    (source / ".env").write_text("secret")
    (source / "CLAUDE.md").write_text("content")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = True
    manager = WorkspaceManager(workspace, config_manager)

    manager.import_from(source)

    assert sorted(p.name for p in workspace.iterdir()) == [".gitignore", "CLAUDE.md"]


def test_export_to_respects_gitignore_in_destination_protects_listed_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("new content")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / ".gitignore").write_text(".env\n")
    (destination / ".env").write_text("original secret")
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = True
    manager = WorkspaceManager(workspace, config_manager)

    manager.export_to(destination)

    assert ((destination / ".env").read_text(), (destination / "CLAUDE.md").read_text()) == (
        "original secret",
        "new content",
    )


def test_import_from_with_respect_gitignore_false_imports_gitignored_file(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".gitignore").write_text(".env\n")
    (source / ".env").write_text("secret")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = False
    manager = WorkspaceManager(workspace, config_manager)

    manager.import_from(source)

    assert (workspace / ".env").read_text() == "secret"


def test_export_to_with_respect_gitignore_false_deletes_gitignored_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / ".gitignore").write_text(".env\n")
    (destination / ".env").write_text("original secret")
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = False
    manager = WorkspaceManager(workspace, config_manager)

    manager.export_to(destination)

    assert not (destination / ".env").exists()


def test_export_to_without_gitignore_in_destination_still_succeeds(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("content")
    destination = tmp_path / "destination"
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = True
    manager = WorkspaceManager(workspace, config_manager)

    manager.export_to(destination)

    assert (destination / "CLAUDE.md").read_text() == "content"


def test_import_from_without_gitignore_in_source_still_succeeds(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "CLAUDE.md").write_text("content")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = True
    manager = WorkspaceManager(workspace, config_manager)

    manager.import_from(source)

    assert (workspace / "CLAUDE.md").read_text() == "content"


def test_export_gitignore_filter_args_empty_for_remote_destination_string(tmp_path):
    config_manager = ConfigManager(tmp_path / "config.toml")
    config_manager.config["respect_gitignore"] = True
    manager = WorkspaceManager(tmp_path, config_manager)

    assert manager._export_gitignore_filter_args("user@host:/pfad") == []

@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (">f+++++++ CLAUDE.md\n", True),
        ("cd+++++++ sub/\n", True),
        ("*deleting alt.txt\n", True),
        ("sending incremental file list\n", False),
        ("created directory backup\n", False),
    ],
)
def test_is_rsync_item_line(line, expected):
    assert _is_rsync_item_line(line) is expected


def test_format_progress_shows_percent_and_counts():
    assert _format_progress("Export", 1, 4) == "\r  Export:  25 % (1/4)"


def test_format_progress_clamps_when_done_exceeds_total():
    assert _format_progress("Import", 5, 4) == "\r  Import: 100 % (4/4)"


def test_export_to_prints_full_progress(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("content")
    manager = WorkspaceManager(workspace)

    manager.export_to(tmp_path / "backup")

    assert "Export: 100 %" in capsys.readouterr().out
