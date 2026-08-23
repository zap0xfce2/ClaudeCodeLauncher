import tomllib

import pytest

from claude_code_launcher import toml_io


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
    assert toml_io._toml_scalar(value) == expected


def test_toml_scalar_raises_type_error_for_unsupported_type():
    with pytest.raises(TypeError):
        toml_io._toml_scalar({"unsupported": "dict"})


def test_toml_table_block_builds_header_and_key_value_lines():
    assert toml_io._toml_table_block("claude_env", {"FOO": "bar"}) == '[claude_env]\nFOO = "bar"'


def test_toml_array_of_tables_block_builds_repeated_blocks():
    entries = [{"path": "/a", "type": "export"}, {"path": "/b", "type": "import"}]
    expected = '[[history]]\npath = "/a"\ntype = "export"\n\n[[history]]\npath = "/b"\ntype = "import"'
    assert toml_io._toml_array_of_tables_block("history", entries) == expected


def test_dump_toml_roundtrips_through_tomllib():
    data = {
        "max_history_entries": 10,
        "ask_for_reset": True,
        "export_ignore_patterns": [".git", "*.pyc"],
        "claude_env": {"FOO": "bar"},
        "history": [{"path": "/a", "type": "export"}, {"path": "/b", "type": "import"}],
    }
    assert tomllib.loads(toml_io._dump_toml(data)) == data
