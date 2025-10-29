import os
import sys
from pathlib import Path

# Third party library imports
from loguru import logger


def _format_message(record):
    """Custom formatter with compact symbols and colors."""
    level_name = record["level"].name

    # Map levels to symbols and colors
    symbols = {
        "TRACE": ("<dim>[*]</dim>", "dim"),
        "DEBUG": ("<dim>[*]</dim>", "dim"),
        "INFO": ("<white>[i]</white>", "white"),
        "SUCCESS": ("<green>[+]</green>", "green"),
        "WARNING": ("<yellow>[!]</yellow>", "yellow"),
        "ERROR": ("<red>[-]</red>", "red"),
        "CRITICAL": ("<red><bold>[X]</bold></red>", "red"),
    }

    symbol, color = symbols.get(level_name, ("[?]", "white"))

    # Professional format: full UTC timestamp + symbol + message
    return (
        "<dim>{time:YYYY-MM-DD HH:mm:ss.SSS!UTC} (UTC)</dim> "
        f"{symbol} "
        f"<{color}>{{message}}</{color}>\n"
        "{exception}"
    )


def _xdg_state_dir(app_name: str = "toboggan") -> Path:
    """Get platform-appropriate log directory following XDG standards."""
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


def setup_logging(level: str = "INFO"):
    """
    Setup logging with compact, visually intuitive output.

    Args:
        level: Log level (TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL)
    """
    level = level.upper()

    # Validate log level
    valid_levels = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
    if level not in valid_levels:
        level = "INFO"

    # Remove all Loguru handlers to avoid duplicates
    logger.remove()

    # Add custom formatted handler
    # enqueue=False for synchronous output to maintain ordering when using print()
    logger.add(
        sys.stderr,
        enqueue=False,
        backtrace=True,
        diagnose=True,
        level=level,
        format=_format_message,
        colorize=True,
    )

    # --- File handler (rotating, UTC timestamps)
    log_dir = _xdg_state_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "toboggan.log"

    # Configurable rotation & retention
    max_bytes = os.getenv("TOBOGGAN_LOG_MAX_BYTES", "10 MB")
    retention_days = int(os.getenv("TOBOGGAN_LOG_RETENTION_DAYS", "14"))

    # File format without colors
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS!UTC} (UTC) "
        "[{level:7}] {message}\n"
        "{exception}"
    )

    logger.add(
        log_file,
        format=file_format,
        level=level,
        rotation=max_bytes,
        retention=f"{retention_days} days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,  # Thread-safe
    )

    logger.debug(f"Logger initialized at level {level}")
    logger.debug(
        f"Log file: {log_file} (rotation {max_bytes}, retention {retention_days} days)"
    )
