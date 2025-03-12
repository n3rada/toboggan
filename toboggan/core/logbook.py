import logging
import os
from datetime import datetime
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
        local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        levelname = record.levelname
        color = self.COLORS.get(levelname, self.RESET)

        return f"[{local_time}] [{color}{levelname}{self.RESET}] {record.getMessage()}"


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
    if "toboggan_logger" in logging.Logger.manager.loggerDict:
        return logging.getLogger("toboggan")

    logger = logging.getLogger("toboggan")

    # Define the SUCCESS log level (between INFO (20) and WARNING (30))
    success_level = 25
    logging.addLevelName(success_level, "SUCCESS")

    if logger.hasHandlers():
        logger.handlers.clear()

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logger.info(f"Setting log level at: {log_level}")

    logger.setLevel(getattr(logging, log_level, logging.INFO))

    ch = logging.StreamHandler()
    ch.setLevel(logger.level)
    ch.setFormatter(ToboLogger())
    logger.addHandler(ch)

    fh = logging.FileHandler(get_log_directory() / "toboggan.log")
    fh.setLevel(logger.level)
    fh.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )
    )
    logger.addHandler(fh)

    # Extend the logger with a `success` method
    def success(self, message, *args, **kwargs):
        if self.isEnabledFor(success_level):
            self._log(success_level, message, args, **kwargs)

    logging.Logger.success = success

    return logger
