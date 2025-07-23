from pathlib import Path
from typing import Set, Optional


class Binary:
    def __init__(self, path: Path):
        self._path = path.resolve()

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def path(self) -> Path:
        return self._path

    def read_bytes(self) -> bytes:
        return self._path.read_bytes()

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"<Binary: {self.name}>"


class BinaryManager:
    def __init__(self, os: str = "unix", binaries_dir: Optional[Path] = None):
        self._binaries_dir = binaries_dir or Path(__file__).parent / "binaries" / os
        self._binaries_dir = self._binaries_dir.resolve()
        self._available: Set[Binary] = set()
        self._scan_binaries()

    def _scan_binaries(self):
        if not self._binaries_dir.exists():
            return
        for file in self._binaries_dir.iterdir():
            if file.is_file() and file.stat().st_mode & 0o111:  # is executable
                self._available.add(Binary(file))

    def list(self) -> Set[str]:
        return {binary.name for binary in self._available}

    def get(self, name: str) -> Optional[Binary]:
        for binary in self._available:
            if binary.name == name:
                return binary
        return None
