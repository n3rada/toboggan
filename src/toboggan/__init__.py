import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("toboggan")
except PackageNotFoundError:
    # Fallback: read directly from pyproject.toml for development
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            __version__ = pyproject_data["project"]["version"] + "-dev"
    except (FileNotFoundError, KeyError):
        __version__ = "unknown"

__all__ = ["__version__"]
