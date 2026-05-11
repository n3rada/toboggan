# tests/test_logbook.py

import os
from pathlib import Path
from unittest import mock

import pytest

from toboggan.core.utils.logbook import _xdg_state_dir

_IS_WINDOWS = os.name == "nt"


class TestXdgStateDir:
    """Tests for _xdg_state_dir covering both POSIX and Windows code paths.

    Windows tests are skipped on POSIX (WindowsPath can't be instantiated)
    and vice versa. The override test runs everywhere.
    """

    def test_override_env(self):
        with mock.patch.dict(
            os.environ, {"TOBOGGAN_LOG_DIR": "/custom/logs"}, clear=False
        ):
            result = _xdg_state_dir()
            assert result == Path("/custom/logs")

    # -- POSIX ---------------------------------------------------------------

    @pytest.mark.skipif(_IS_WINDOWS, reason="POSIX paths only")
    def test_xdg_state_home_posix(self):
        env = {"XDG_STATE_HOME": "/xdg/state"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            result = _xdg_state_dir()
            assert result == Path("/xdg/state/toboggan/logs")

    @pytest.mark.skipif(_IS_WINDOWS, reason="POSIX paths only")
    def test_default_posix(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            os.environ.pop("XDG_STATE_HOME", None)
            result = _xdg_state_dir()
            assert result == Path.home() / ".local" / "state" / "toboggan" / "logs"

    @pytest.mark.skipif(_IS_WINDOWS, reason="POSIX paths only")
    def test_custom_app_name_posix(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            os.environ.pop("XDG_STATE_HOME", None)
            result = _xdg_state_dir("myapp")
            assert result == Path.home() / ".local" / "state" / "myapp" / "logs"

    # -- Windows -------------------------------------------------------------

    @pytest.mark.skipif(not _IS_WINDOWS, reason="Windows paths only")
    def test_windows_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            os.environ.pop("LOCALAPPDATA", None)
            result = _xdg_state_dir()
            expected = (
                Path.home() / "AppData" / "Local" / "toboggan" / "logs"
            ).resolve()
            assert result == expected

    @pytest.mark.skipif(not _IS_WINDOWS, reason="Windows paths only")
    def test_windows_localappdata_env(self):
        env = {"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            result = _xdg_state_dir()
            expected = (
                Path("C:\\Users\\test\\AppData\\Local") / "toboggan" / "logs"
            ).resolve()
            assert result == expected
