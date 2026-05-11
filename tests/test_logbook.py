# tests/test_logbook.py

import os
from pathlib import Path
from unittest import mock

from toboggan.core.utils.logbook import _xdg_state_dir


class TestXdgStateDir:
    def test_override_env(self):
        with mock.patch.dict(os.environ, {"TOBOGGAN_LOG_DIR": "/custom/logs"}, clear=False):
            result = _xdg_state_dir()
            assert result == Path("/custom/logs")

    def test_xdg_state_home(self):
        env = {"XDG_STATE_HOME": "/xdg/state"}
        with mock.patch.dict(os.environ, env, clear=False):
            # Clear override
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            if os.name != "nt":
                result = _xdg_state_dir()
                assert result == Path("/xdg/state/toboggan/logs")

    def test_default_posix(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            os.environ.pop("XDG_STATE_HOME", None)
            if os.name != "nt":
                result = _xdg_state_dir()
                assert result == Path.home() / ".local" / "state" / "toboggan" / "logs"

    def test_custom_app_name(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOBOGGAN_LOG_DIR", None)
            os.environ.pop("XDG_STATE_HOME", None)
            if os.name != "nt":
                result = _xdg_state_dir("myapp")
                assert result == Path.home() / ".local" / "state" / "myapp" / "logs"
