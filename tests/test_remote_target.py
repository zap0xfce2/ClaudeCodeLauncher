import pytest

from claude_code_launcher.remote_target import _is_remote_target, _remote_path_part


@pytest.mark.parametrize(
    ("path_str", "expected"),
    [
        ("user@host:/srv/backup", True),
        ("host:/srv/backup", True),
        ("host:relative/path", True),
        ("/local/absolute/path", False),
        ("relative/local/path", False),
        ("~/local/path", False),
        ("rsync://host/module/path", False),
    ],
)
def test_is_remote_target(path_str, expected):
    assert _is_remote_target(path_str) is expected


def test_remote_path_part_strips_host_prefix():
    assert _remote_path_part("user@host:/srv/backup/file.md") == "/srv/backup/file.md"


def test_remote_path_part_strips_host_prefix_without_user():
    assert _remote_path_part("host:relative/path") == "relative/path"
