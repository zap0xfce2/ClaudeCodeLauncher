"""SSH-Style rsync-Remote-Ziele erkennen (user@host:/pfad, host:/pfad – kein rsync://-Daemon-Syntax)."""

import re

# Doppelpunkt vor dem ersten "/", kein führendes "/", optionales "user@".
# (?!//) schließt rsync://-Daemon-Syntax explizit aus (bewusst nicht unterstützt).
_SSH_REMOTE_TARGET_PATTERN = re.compile(r"^(?:[^/@\s]+@)?[^/\s:]+:(?!//)")


def _is_remote_target(path_str: str) -> bool:
    """True für SSH-Style rsync-Ziele wie 'user@host:/pfad' oder 'host:/pfad'."""
    return bool(_SSH_REMOTE_TARGET_PATTERN.match(path_str))


def _remote_path_part(path_str: str) -> str:
    """Pfad-Anteil nach dem ersten ':' (für Suffix-Heuristik und Dateinamen-Extraktion).

    Bekannte, akzeptierte Grenze (identisch zu scp/rsync selbst): ein lokaler
    Dateiname ohne "/" aber mit ":" (z. B. "notes:v2.md") wird fälschlich als
    Remote-Ziel erkannt – dieselbe Ambiguität wie bei den Original-Tools.
    """
    return path_str.partition(":")[2]
