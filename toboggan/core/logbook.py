import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler


class ToboLogger(logging.Formatter):
    """Toboggan's custom logger with colors, timestamps (UTC), and structured output."""

    COLORS = {
        "DEBUG": "\033[37m",  # Light Gray
        "INFO": "\033[96m",  # Cyan
        "SUCCESS": "\033[92m",  # Green
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",  # Red
        "CRITICAL": "\033[95m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, color: bool = True):
        super().__init__()
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        levelname = record.levelname
        color_prefix = self.COLORS.get(levelname, "") if self.color else ""
        color_reset = self.RESET if self.color else ""

        formatted = f"[{utc_time} (UTC)] [{color_prefix}{levelname}{color_reset}] {record.getMessage()}"

        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


def _xdg_state_dir(app_name: str = "toboggan") -> Path:
    # Highest priority: explicit override
    override = os.getenv("TOBOGGAN_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return (base / app_name / "logs").resolve()

    # POSIX: follow XDG
    base = os.getenv("XDG_STATE_HOME")
    if base:
        return Path(base).expanduser().resolve() / app_name / "logs"

    return Path.home() / ".local" / "state" / app_name / "logs"


def _is_tty(stream) -> bool:
    try:
        return stream.isatty()
    except Exception:
        return False


def _cleanup_old_logs(log_file: Path, retention_days: int) -> None:
    """Delete rotated files older than retention_days."""
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    prefix = log_file.name + "."
    for p in log_file.parent.glob(log_file.name + ".*"):
        # RotatingFileHandler names like: toboggan.log.1, .2, or .1.gz if compressed externally
        try:
            # If file has mtime older than cutoff, remove
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                p.unlink(missing_ok=True)
        except Exception:
            # best-effort cleanup; ignore failures
            pass


def get_logger() -> logging.Logger:
    """Returns a singleton logger configured with colorful console + rotating file."""
    existing = logging.Logger.manager.loggerDict.get("toboggan")
    if isinstance(existing, logging.Logger):
        return logging.getLogger("toboggan")

    logger = logging.getLogger("toboggan")

    # --- Custom SUCCESS level (between INFO and WARNING)
    SUCCESS_LEVEL = 25
    logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")

    if logger.hasHandlers():
        logger.handlers.clear()

    # --- Level from env (default INFO)
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logger.setLevel(log_level)

    # --- Console handler (colorful)
    force_color = os.getenv("TOBOGGAN_COLOR", "").strip() == "1"
    colorize = force_color or _is_tty(sys.stderr)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(log_level)
    ch.setFormatter(ToboLogger(color=colorize))
    logger.addHandler(ch)

    # --- File handler (rotating, UTC timestamps)
    log_dir = _xdg_state_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "toboggan.log"

    # Configurable rotation & retention
    max_bytes = int(os.getenv("TOBOGGAN_LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB
    backup_count = int(
        os.getenv("TOBOGGAN_LOG_BACKUP_COUNT", "10")
    )  # number of rotated files to keep
    retention_days = int(
        os.getenv("TOBOGGAN_LOG_RETENTION_DAYS", "14")
    )  # days to retain (extra cleanup)

    class UtcFormatter(logging.Formatter):
        converter = time.gmtime  # force UTC in asctime

        def formatTime(self, record, datefmt=None):
            ct = self.converter(record.created)
            if datefmt:
                s = time.strftime(datefmt, ct)
            else:
                t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
                s = f"{t}"
            return s

    file_formatter = UtcFormatter(
        fmt="[{asctime} (UTC)] [{levelname}] {message}",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="{",
    )

    fh = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    fh.setLevel(log_level)
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    # Extra: prune very old rotated files by age
    _cleanup_old_logs(log_file, retention_days=retention_days)

    # Add logger.success method
    def success(self, message, *args, **kwargs):
        if self.isEnabledFor(SUCCESS_LEVEL):
            self._log(SUCCESS_LEVEL, message, args, **kwargs)

    logging.Logger.success = success  # type: ignore[attr-defined]

    logger.debug(f"Logger initialized at level {logging.getLevelName(log_level)}")
    logger.debug(
        f"Log file: {log_file} (rotation {max_bytes} bytes, backups {backup_count}, retention {retention_days} days)"
    )
    return logger
