from claude_code_launcher.session_banner import _banner_top_offset


def test_banner_top_offset_centers_vertically():
    assert _banner_top_offset(24, 6) == 9


def test_banner_top_offset_never_negative():
    assert _banner_top_offset(4, 10) == 0
