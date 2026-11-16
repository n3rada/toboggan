# tests/test_logbook.py

import json
import os
from pathlib import Path
from unittest import mock

import pytest
from loguru import logger

from toboggan.core.utils.logbook import _xdg_state_dir, setup_logging

_IS_WINDOWS = os.name == "nt"


class TestJsonlFileSink:
    """The persistent log file is JSONL: one flat JSON object per line."""

    @pytest.fixture
    def log_file(self, tmp_path):
        with mock.patch.dict(
            os.environ, {"TOBOGGAN_LOG_DIR": str(tmp_path)}, clear=False
        ):
            setup_logging("TRACE")
        yield tmp_path / "toboggan.jsonl"
        # Flushes the enqueued file sink and releases the file handle.
        logger.remove()

    def _read_entries(self, path: Path) -> list[dict]:
        logger.remove()
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def test_every_line_is_json(self, log_file):
        logger.info("first")
        logger.warning("second")

        entries = self._read_entries(log_file)
        messages = [entry["msg"] for entry in entries]

        assert "first" in messages
        assert "second" in messages

    def test_entry_schema(self, log_file):
        logger.success("schema check")

        entry = next(
            e for e in self._read_entries(log_file) if e["msg"] == "schema check"
        )

        assert entry["level"] == "SUCCESS"
        assert entry["module"] == __name__
        assert entry["function"] == "test_entry_schema"
        assert isinstance(entry["line"], int)
        assert entry["exception"] is None
        assert entry["ts"].endswith("Z")
        assert "extra" not in entry

    def test_multiline_message_stays_on_one_line(self, log_file):
        logger.info("uid=0(root)\ngid=0(root)\n{braces} stay literal")

        entry = next(
            e for e in self._read_entries(log_file) if e["msg"].startswith("uid=0")
        )

        assert entry["msg"] == "uid=0(root)\ngid=0(root)\n{braces} stay literal"

    def test_exception_is_serialized(self, log_file):
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("failed")

        entry = next(e for e in self._read_entries(log_file) if e["msg"] == "failed")

        assert entry["level"] == "ERROR"
        assert "ValueError: boom" in entry["exception"]
        assert "Traceback" in entry["exception"]

    def test_bound_extra_is_included(self, log_file):
        logger.bind(action="upload", size=42).info("with extra")

        entry = next(
            e for e in self._read_entries(log_file) if e["msg"] == "with extra"
        )

        assert entry["extra"] == {"action": "upload", "size": 42}


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
            # The override is resolved to an absolute path (on Windows this
            # prepends the current drive, e.g. C:\custom\logs).
            assert result == Path("/custom/logs").resolve()
            assert result.is_absolute()

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
