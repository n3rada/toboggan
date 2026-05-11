# tests/test_banner.py

from toboggan.banner import display_banner
from toboggan import __version__


class TestBanner:
    def test_contains_version(self):
        banner = display_banner()
        assert __version__ in banner

    def test_contains_author(self):
        banner = display_banner()
        assert "@n3rada" in banner

    def test_returns_string(self):
        assert isinstance(display_banner(), str)
