"""TOML-Serialisierung für ConfigManager – deckt nur die im Config-Schema vorkommenden Typen ab."""

import json
from typing import Any


def _toml_scalar(value: Any) -> str:
    """Wandelt einen skalaren Config-Wert oder eine Liste von Strings in TOML-Literal-Syntax um."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Nicht unterstützter Config-Typ für TOML: {type(value)}")


def _toml_table_block(name: str, table: dict[str, str]) -> str:
    """Baut einen [name]-Tabellenblock aus einem flachen Dict (z. B. claude_env)."""
    lines = [f"[{name}]"]
    lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in table.items())
    return "\n".join(lines)


def _toml_array_of_tables_block(name: str, entries: list[dict[str, Any]]) -> str:
    """Baut wiederholte [[name]]-Blöcke aus einer Liste flacher Dicts (z. B. history)."""
    blocks = []
    for entry in entries:
        lines = [f"[[{name}]]"]
        lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in entry.items())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _dump_toml(data: dict[str, Any]) -> str:
    """Serialisiert das Config-Dict als TOML.

    Kein generischer TOML-Writer: Skalare/Listen von Strings werden als flache
    key = value Zeilen geschrieben (müssen vor jedem Tabellenblock stehen), ein
    dict[str, str] als [key]-Tabelle, eine nicht-leere list[dict] als [[key]].
    """
    scalar_lines = []
    table_blocks = []
    for key, value in data.items():
        if isinstance(value, dict):
            table_blocks.append(_toml_table_block(key, value))
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            table_blocks.append(_toml_array_of_tables_block(key, value))
        else:
            scalar_lines.append(f"{key} = {_toml_scalar(value)}")

    sections = ["\n".join(scalar_lines), *table_blocks]
    return "\n\n".join(section for section in sections if section) + "\n"
