import subprocess

from claude_code_launcher.session_banner import _banner_top_offset, _render_art


def test_banner_top_offset_centers_vertically():
    assert _banner_top_offset(24, 6) == 9


def test_banner_top_offset_never_negative():
    assert _banner_top_offset(4, 10) == 0


def test_render_art_passes_name_after_option_terminator(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="art\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _render_art("-v", 80)
    assert calls[0][-2:] == ["--", "-v"]
