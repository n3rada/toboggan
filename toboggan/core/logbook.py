import logging
import os
from datetime import datetime, timezone
from pathlib import Path


class ToboLogger(logging.Formatter):
    """Toboggan's custom logger with colors, timestamps, and structured output."""

    COLORS = {
        "DEBUG": "\033[37m",  # Light Gray
        "INFO": "\033[96m",  # Cyan
        "SUCCESS": "\033[92m",  # Green
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",  # Red
        "CRITICAL": "\033[95m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        levelname = record.levelname
        color = self.COLORS.get(levelname, self.RESET)

        formatted = (
            f"[{utc_time} (UTC)] [{color}{levelname}{self.RESET}] {record.getMessage()}"
        )

        if record.exc_info:
            # Append formatted traceback if present
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


def get_log_directory():
    """Return the proper log directory based on the OS and user privileges."""
    if os.name == "nt":
        log_dir = (
            Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            / "toboggan"
            / "logs"
        )
    else:
        if os.geteuid() == 0:
            log_dir = Path("/var/log/toboggan")
        else:
            # Running as a user, follow XDG spec
            log_dir = (
                Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
                / "toboggan"
                / "logs"
            )

    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_logger():
    """Returns a singleton instance of the logger to be shared across all modules."""

    if "toboggan" in logging.Logger.manager.loggerDict:
        return logging.getLogger("toboggan")

    logger = logging.getLogger("toboggan")

    # Define the SUCCESS log level (between INFO (20) and WARNING (30))
    success_level = 25
    logging.addLevelName(success_level, "SUCCESS")

    if logger.hasHandlers():
        logger.handlers.clear()

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # --- Stream handler with color ---
    ch = logging.StreamHandler()
    ch.setLevel(logger.level)
    ch.setFormatter(ToboLogger())  # colored formatter for console
    logger.addHandler(ch)

    # --- File handler without color ---
    log_file = get_log_directory() / "toboggan.log"
    file_formatter = logging.Formatter(
        fmt="[{asctime} (UTC)] [{levelname}] {message}",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="{",
    )

    fh = logging.FileHandler(log_file)
    fh.setLevel(logger.level)
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    # Add custom success level
    def success(self, message, *args, **kwargs):
        if self.isEnabledFor(success_level):
            self._log(success_level, message, args, **kwargs)

    logging.Logger.success = success

    return logger
