# tests/test_target.py

import pytest
from toboggan.core.target import Target


class TestTargetInit:
    def test_basic_init(self):
        t = Target(os="linux", user="www-data", hostname="web01", pwd="/var/www")
        assert t.os == "linux"
        assert t.user == "www-data"
        assert t.hostname == "web01"
        assert t.pwd == "/var/www"

    def test_user_filtered_on_not_found(self):
        t = Target(os="linux", user="whoami: not found")
        assert t.user is None

    def test_user_filtered_on_introuvable(self):
        t = Target(os="linux", user="whoami: commande introuvable")
        assert t.user is None

    def test_hostname_filtered_on_not_found(self):
        t = Target(os="linux", hostname="hostname: not found")
        assert t.hostname is None

    def test_hostname_filtered_on_introuvable(self):
        t = Target(os="linux", hostname="hostname: introuvable")
        assert t.hostname is None

    def test_none_user_stays_none(self):
        t = Target(os="linux", user=None)
        assert t.user is None

    def test_none_hostname_stays_none(self):
        t = Target(os="linux", hostname=None)
        assert t.hostname is None

    def test_valid_user_preserved(self):
        t = Target(os="linux", user="root")
        assert t.user == "root"


class TestArchitectureDetection:
    @pytest.mark.parametrize(
        "info, expected",
        [
            ("Linux web01 5.15.0-91-generic #101 SMP x86_64 GNU/Linux", "x86_64"),
            ("Linux arm-box 5.4.0 aarch64 GNU/Linux", "aarch64"),
            ("Linux arm-box 5.4.0 arm64 GNU/Linux", "aarch64"),
            ("Linux old 4.4.0 i686 GNU/Linux", "x86"),
            ("Linux old 4.4.0 i386 GNU/Linux", "x86"),
            ("Linux generic 5.4.0 amd64", "x86_64"),
            ("something with 64 in it", "x86_64"),
            ("unknown arch string", None),
        ],
    )
    def test_architecture_from_system_info(self, info, expected):
        t = Target(os="linux", system_info=info)
        assert t.architecture == expected

    def test_no_system_info(self):
        t = Target(os="linux")
        assert t.architecture is None

    def test_system_info_setter_updates_arch(self):
        t = Target(os="linux")
        assert t.architecture is None
        t.system_info = "Linux box 5.15 x86_64"
        assert t.architecture == "x86_64"

    def test_system_info_setter_to_none(self):
        t = Target(os="linux", system_info="x86_64")
        assert t.architecture == "x86_64"
        t.system_info = None
        assert t.architecture is None
