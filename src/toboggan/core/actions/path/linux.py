# External library imports
from loguru import logger

# Local library imports
from .core.action import BaseAction


class PathAction(BaseAction):
    """
    Inspect the remote PATH environment variable.

    This action prints the current contents of the PATH variable from the target system,
    providing insight into the order in which binaries and scripts are located during execution.

    Use this to:
    - Identify binary hijack opportunities.
    - Spot suspicious or non-standard directories.
    - Debug misconfigured environments (e.g., missing /usr/bin).

    Example output:
        1. /usr/local/sbin
        2. /usr/local/bin
        3. /usr/sbin
        ...
    """

    DESCRIPTION = "List the remote system's PATH entries and their lookup order."

    def run(self):
        try:
            raw_path = self._executor.remote_execute(command="/bin/echo $PATH").strip()

            if not raw_path:
                logger.warning("⚠️ No PATH variable found or command failed.")
                return

            path_entries = raw_path.split(":")
            unique_paths = list(dict.fromkeys(path_entries))  # Preserves order

            logger.info("📂 Remote PATH variable lookup order:")
            for index, entry in enumerate(unique_paths, start=1):
                print(f"   {index}. {entry}")

            logger.debug(f"Full PATH string: {raw_path!r}")

        except Exception as exc:
            logger.error(f"❌ Failed to read remote PATH variable: {exc}")
