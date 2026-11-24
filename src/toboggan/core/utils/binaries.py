# toboggan/core/utils/binaries.py

# Built-in imports
from __future__ import annotations

import hashlib
import io
import os
import re
import tarfile
from pathlib import Path
from typing import ClassVar

# External library imports
import httpx
from loguru import logger


class BinaryFetcher:
    """Fetch and cache pinned standalone binaries for explicit target deployment."""

    BASE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "toboggan" / "binaries"
    ARCHITECTURES: ClassVar[dict[str, str]] = {
        "386": "x86",
        "aarch64": "aarch64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "i386": "x86",
        "i686": "x86",
        "x64": "x86_64",
        "x86": "x86",
        "x86-64": "x86_64",
        "x86_64": "x86_64",
    }
    CURL_VARIANTS: ClassVar[dict[str, str]] = {
        "aarch64": "aarch64",
        "x86": "i686",
        "x86_64": "x86_64",
    }
    KUBECTL_VARIANTS: ClassVar[dict[str, str]] = {
        "aarch64": "arm64",
        "x86": "386",
        "x86_64": "amd64",
    }
    BUSYBOX_VERSION = "1.35.0"
    BUSYBOX_VARIANTS: ClassVar[dict[str, tuple[str, str]]] = {
        "x86": ("1.35.0-i686-linux-musl", "27e409705b29937b9a6105038d9c2e3eb8dc3e2c8d606d22872dbde7f47c000f"),
        "x86_64": ("1.35.0-x86_64-linux-musl", "6e123e7f3202a8c1e9b1f94d8941580a25135382b99e8d3e34fb858bba311348"),
    }

    @classmethod
    def list_available(cls) -> list[str]:
        """Return supported prebuilt binary names."""
        return ["busybox", "curl", "kubectl"]

    def __init__(self, os_name: str = "linux", arch: str = "x86_64") -> None:
        self._os = os_name.lower()
        if self._os != "linux":
            raise ValueError("Static binary deployment currently supports Linux only.")
        try:
            self._arch = self.ARCHITECTURES[arch.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported architecture: {arch}") from exc

    def get(self, name: str) -> Path | None:
        """Return a verified cached binary or fetch its pinned build."""
        match name.lower():
            case "busybox":
                return self._fetch_busybox()
            case "curl":
                return self._fetch_curl()
            case "kubectl":
                return self._fetch_kubectl()
            case _:
                raise ValueError(f"Unknown binary: {name}")

    def _destination(self, name: str, version: str) -> Path:
        """Return the versioned operating-system and architecture cache path."""
        return self.BASE_DIR / name / version / f"{self._os}-{self._arch}" / name

    @staticmethod
    def _verified(data: bytes, expected_sha256: str) -> bool:
        """Return whether binary bytes match the pinned SHA-256 digest."""
        return hashlib.sha256(data).hexdigest() == expected_sha256

    def _cached(self, destination: Path, expected_sha256: str) -> Path | None:
        """Return a valid cached file and ignore corrupt or incomplete entries."""
        logger.trace(f"Checking static binary cache: {destination}")
        if not destination.is_file():
            return None
        try:
            if self._verified(destination.read_bytes(), expected_sha256):
                destination.chmod(0o755)
                logger.debug(f"Using verified cached binary: {destination}")
                return destination
        except OSError:
            pass
        logger.warning(f"Ignoring invalid cached binary: {destination}")
        return None

    def _save(self, name: str, version: str, data: bytes, expected_sha256: str) -> Path | None:
        """Verify and store fetched binary bytes in the versioned cache."""
        logger.info(f"Verifying SHA-256 for {name} {version}.")
        if not self._verified(data, expected_sha256):
            logger.error(f"SHA-256 verification failed for {name} {version}.")
            return None
        destination = self._destination(name, version)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755)
        destination.with_name(f"{name}.sha256").write_text(f"{expected_sha256}\n", encoding="ascii")
        logger.success(f"{name} {version} saved to: {destination}")
        return destination

    def _latest_cached(self, name: str) -> Path | None:
        """Return the most recently stored valid build for this target."""
        candidates = sorted(
            self.BASE_DIR.glob(f"{name}/*/{self._os}-{self._arch}/{name}"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            checksum = candidate.with_name(f"{name}.sha256")
            try:
                expected = checksum.read_text(encoding="ascii").strip()
            except OSError:
                continue
            cached = self._cached(candidate, expected)
            if cached:
                logger.warning(f"Using cached {name} because release lookup failed: {cached}")
                return cached
        return None

    @staticmethod
    def _download(url: str) -> bytes:
        """Download one explicit release asset using operator-controlled TLS trust."""
        logger.info(f"Downloading static binary data from: {url}")
        response = httpx.get(url, timeout=30.0, verify=False, follow_redirects=True)
        response.raise_for_status()
        logger.debug(f"Downloaded {len(response.content)} bytes from: {url}")
        return response.content

    @classmethod
    def _download_text(cls, url: str) -> str:
        """Download UTF-8 release metadata using the configured trust model."""
        return cls._download(url).decode("utf-8").strip()

    @staticmethod
    def _curl_checksum(body: str, arch: str) -> str:
        """Extract the Linux glibc binary SHA-256 from static-curl release notes."""
        match = re.search(
            rf"\|\s*curl\s*\|\s*linux\s*\|\s*{re.escape(arch)}\s*"
            r"\|\s*glibc\s*\|\s*([0-9a-fA-F]{64})\s*\|",
            body,
        )
        if not match:
            raise ValueError("static-curl release has no matching SHA-256.")
        return match.group(1).lower()

    def _fetch_curl(self) -> Path | None:
        """Resolve and verify the latest static-curl glibc build."""
        variant = self.CURL_VARIANTS[self._arch]
        try:
            metadata_url = "https://api.github.com/repos/stunnel/static-curl/releases/latest"
            logger.info(f"Resolving the latest static-curl release from: {metadata_url}")
            metadata = httpx.get(
                metadata_url,
                timeout=10.0,
                verify=False,
                follow_redirects=True,
            )
            metadata.raise_for_status()
            release = metadata.json()
            version = release["tag_name"]
            if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9]+", version):
                raise ValueError("static-curl release has an invalid version tag.")
            filename = f"curl-linux-{variant}-glibc-{version}.tar.xz"
            asset = next(item for item in release["assets"] if item["name"] == filename)
            expected_url = f"https://github.com/stunnel/static-curl/releases/download/{version}/"
            if not asset["browser_download_url"].startswith(expected_url):
                raise ValueError("static-curl release has an invalid asset URL.")
            expected = self._curl_checksum(release.get("body", ""), variant)
            logger.debug(f"Resolved curl {version} for {self._os}/{self._arch}; SHA-256 {expected}.")
            destination = self._destination("curl", version)
            cached = self._cached(destination, expected)
            if cached:
                return cached
            archive = self._download(asset["browser_download_url"])
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tar:
                members = [
                    member for member in tar.getmembers() if member.isfile() and Path(member.name).name == "curl"
                ]
                if len(members) != 1:
                    raise ValueError("curl archive must contain exactly one curl binary.")
                source = tar.extractfile(members[0])
                if source is None:
                    raise ValueError("curl binary cannot be read from its archive.")
                return self._save("curl", version, source.read(), expected)
        except Exception as exc:
            logger.warning(f"Latest curl lookup or retrieval failed: {exc}")
            return self._latest_cached("curl")

    def _fetch_kubectl(self) -> Path | None:
        """Resolve and verify the current stable Kubernetes kubectl build."""
        variant = self.KUBECTL_VARIANTS[self._arch]
        try:
            logger.info("Resolving the current stable kubectl release.")
            version = self._download_text("https://dl.k8s.io/release/stable.txt")
            if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", version):
                raise ValueError("Kubernetes stable.txt has an invalid version.")
            base_url = f"https://dl.k8s.io/release/{version}/bin/linux/{variant}"
            expected = self._download_text(f"{base_url}/kubectl.sha256")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                raise ValueError("kubectl release has an invalid SHA-256.")
            logger.debug(f"Resolved kubectl {version} for {self._os}/{self._arch}; SHA-256 {expected.lower()}.")
            destination = self._destination("kubectl", version)
            cached = self._cached(destination, expected)
            if cached:
                return cached
            return self._save("kubectl", version, self._download(f"{base_url}/kubectl"), expected.lower())
        except Exception as exc:
            logger.warning(f"Stable kubectl lookup or retrieval failed: {exc}")
            return self._latest_cached("kubectl")

    def _fetch_busybox(self) -> Path | None:
        """Fetch the pinned official static BusyBox build when one is available."""
        try:
            variant, expected = self.BUSYBOX_VARIANTS[self._arch]
        except KeyError as exc:
            raise ValueError(f"BusyBox {self.BUSYBOX_VERSION} is unavailable for {self._arch}.") from exc
        destination = self._destination("busybox", self.BUSYBOX_VERSION)
        logger.info(f"Using official BusyBox fallback {self.BUSYBOX_VERSION} for {self._os}/{self._arch}.")
        logger.debug(f"Expected BusyBox SHA-256: {expected}.")
        cached = self._cached(destination, expected)
        if cached:
            return cached
        url = f"https://busybox.net/downloads/binaries/{variant}/busybox"
        try:
            return self._save("busybox", self.BUSYBOX_VERSION, self._download(url), expected)
        except Exception as exc:
            logger.error(f"Failed to fetch BusyBox {self.BUSYBOX_VERSION}: {exc}")
            return None
