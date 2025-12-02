# toboggan/core/utils/binaries.py

# Built-in imports
import os
import tempfile
import tarfile
from pathlib import Path

# External library imports
from loguru import logger
import httpx


class BinaryFetcher:
    BASE_DIR = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "toboggan"
        / "binaries"
    )

    @staticmethod
    def list_available() -> list[str]:
        """Returns a list of available binary names."""
        return ["curl", "kubectl"]

    def __init__(self, os: str = "linux", arch: str = "x86-64"):
        self.BASE_DIR.mkdir(parents=True, exist_ok=True)

        self._os = os.lower()
        self._arch = arch.lower()

        if self._os not in ["linux", "windows"]:
            raise ValueError(
                f"❌ Unsupported OS: {self._os}. Only 'linux' and 'windows' are supported."
            )

    def get(self, name: str) -> Path | None:
        """
        Get the path to the binary, downloading it if needed.
        """
        match name:
            case "kubectl":
                return self._fetch_kubectl()
            case "curl":
                return self._fetch_curl()
            case _:
                raise ValueError(f"❌ Unknown binary: {name}")

    def _fetch_kubectl(self) -> Path | None:
        """
        Downloads the latest kubectl binary for Linux x86_64.
        """

        destination = self.BASE_DIR / "kubectl"

        if destination.exists():
            return destination

        if self._arch == "x86-64":
            api_arch = "amd64"
        else:
            api_arch = "arm64"

        try:
            # Step 1: Get latest stable version
            version_resp = httpx.get(
                "https://dl.k8s.io/release/stable.txt",
                timeout=10.0,
                verify=False,
                follow_redirects=True,
            )
            version_resp.raise_for_status()
            version = version_resp.text.strip()

            # Step 2: Build download URL
            binary_url = (
                f"https://dl.k8s.io/release/{version}/bin/{self._os}/{api_arch}/kubectl"
            )

            # Step 3: Download the binary
            logger.info(f"⬇️ Downloading kubectl {version} → {destination}")
            bin_resp = httpx.get(binary_url, timeout=30.0, verify=False)
            bin_resp.raise_for_status()

            # Step 4: Save it
            destination.write_bytes(bin_resp.content)
            destination.chmod(0o755)

            logger.success(f"✅ kubectl saved to: {destination}")
            return destination

        except httpx.HTTPError as exc:
            logger.error(f"❌ Failed to download kubectl: {exc}")
            return None

    def _fetch_curl(self) -> Path | None:
        destination = self.BASE_DIR / "curl"
        if destination.exists():
            return destination

        try:
            # Step 1: Get redirect to latest version
            resp = httpx.get(
                "https://github.com/stunnel/static-curl/releases/latest",
                follow_redirects=False,
                verify=False,
                timeout=10.0,
            )

            if "location" not in resp.headers:
                raise ValueError("No redirect found for latest curl version.")

            latest_tag_url = resp.headers["location"]
            tag = latest_tag_url.rstrip("/").split("/")[-1]

            logger.info(f"Latest cURL tag: {tag}")

            if self._os == "windows":
                filename = f"curl-windows-{self._arch}-{tag}.tar.xz"
            else:
                filename = f"curl-linux-{self._arch}-glibc-{tag}.tar.xz"

            # Step 2: Download tarball
            tar_resp = httpx.get(
                f"https://github.com/stunnel/static-curl/releases/download/{tag}/{filename}",
                timeout=30.0,
                verify=False,
                follow_redirects=True,
            )
            tar_resp.raise_for_status()

            # Step 3: Extract 'curl' from archive
            with tempfile.TemporaryDirectory() as tmpdir:
                archive_path = Path(tmpdir) / filename
                archive_path.write_bytes(tar_resp.content)

                with tarfile.open(archive_path, mode="r:xz") as tar:
                    for member in tar.getmembers():
                        if member.isfile() and Path(member.name).name == "curl":
                            tar.extract(member, path=tmpdir)
                            extracted = Path(tmpdir) / member.name
                            destination.write_bytes(extracted.read_bytes())
                            destination.chmod(0o755)
                            logger.success(f"✅ cURL saved to: {destination}")
                            return destination

                raise FileNotFoundError("curl binary not found in archive.")

        except Exception as e:
            logger.error(f"❌ Failed to fetch curl: {e}")
            return None
