import hashlib
import io
import tarfile

import pytest

from toboggan.core.actions.drop_static.linux import DropStaticBinary
from toboggan.core.helpers.linux import LinuxHelper
from toboggan.core.utils.binaries import BinaryFetcher


@pytest.mark.parametrize(
    ("source", "expected"),
    [("amd64", "x86_64"), ("x86-64", "x86_64"), ("arm64", "aarch64"), ("i686", "x86")],
)
def test_binary_fetcher_normalizes_architecture(source, expected):
    assert BinaryFetcher(arch=source)._arch == expected


def test_binary_fetcher_rejects_unknown_architecture():
    with pytest.raises(ValueError, match="Unsupported architecture"):
        BinaryFetcher(arch="mystery")


def test_binary_cache_path_includes_version_and_architecture(tmp_path, monkeypatch):
    monkeypatch.setattr(BinaryFetcher, "BASE_DIR", tmp_path)

    fetcher = BinaryFetcher(arch="x86_64")

    assert fetcher._destination("curl", "1.2.3") == (tmp_path / "curl" / "1.2.3" / "linux-x86_64" / "curl")


def test_fetch_curl_verifies_and_extracts_binary(tmp_path, monkeypatch):
    binary = b"static curl"
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:xz") as tar:
        member = tarfile.TarInfo("package/bin/curl")
        member.size = len(binary)
        tar.addfile(member, io.BytesIO(binary))

    monkeypatch.setattr(BinaryFetcher, "BASE_DIR", tmp_path)
    monkeypatch.setattr(BinaryFetcher, "CURL_VARIANTS", {"x86_64": "x86_64"})

    class MetadataResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "tag_name": "1.2.3-1",
                "body": (f"| curl | linux | x86_64 | glibc | {hashlib.sha256(binary).hexdigest()} |"),
                "assets": [
                    {
                        "name": "curl-linux-x86_64-glibc-1.2.3-1.tar.xz",
                        "browser_download_url": (
                            "https://github.com/stunnel/static-curl/releases/download/"
                            "1.2.3-1/curl-linux-x86_64-glibc-1.2.3-1.tar.xz"
                        ),
                    }
                ],
            }

    monkeypatch.setattr(
        "toboggan.core.utils.binaries.httpx.get",
        lambda *_args, **_kwargs: MetadataResponse(),
    )
    monkeypatch.setattr(BinaryFetcher, "_download", staticmethod(lambda _url: archive_buffer.getvalue()))

    result = BinaryFetcher().get("curl")

    assert result is not None
    assert result.read_bytes() == binary


def test_register_busybox_replaces_cached_misses():
    class Executor:
        def remote_execute(self, command, **_kwargs):
            assert command == "/tmp/.bb --list"
            return "base64\ncat\ndd\n"

    helper = LinuxHelper(Executor())
    helper.command_location_cache["cat"] = ""

    assert helper.register_busybox("/tmp/.bb") is True
    assert helper.get_command_location("cat") == "/tmp/.bb cat"


def test_drop_static_registers_the_dropped_command(tmp_path, monkeypatch):
    binary = tmp_path / "curl"
    binary.write_bytes(b"curl")

    class Target:
        os = "linux"
        architecture = "x86_64"
        pwd = "/work"

    class Helper:
        def register_command(self, name, path):
            self.registered = (name, path)

    class Executor:
        target = Target()
        os_helper = Helper()
        working_directory = "/tmp/toboggan"

    monkeypatch.setattr(BinaryFetcher, "get", lambda _self, _name: binary)
    monkeypatch.setattr(
        "toboggan.core.actions.drop_static.linux.DropBinary.run",
        lambda _self, **_kwargs: True,
    )

    action = DropStaticBinary(Executor())

    assert action.run("curl") is True
    assert action._os_helper.registered == ("curl", "/tmp/toboggan/curl")
