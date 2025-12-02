# External library imports
from loguru import logger

# Local application/library specific imports
from .core.action import BaseAction


class PrivBinsAction(BaseAction):
    DESCRIPTION = (
        "Lists SUID and SGID binaries that could be exploited for privilege escalation."
    )

    def run(self) -> None:
        """
        Fetches and displays all privileged binaries (SUID & SGID) on the system.
        Prints each section separately.
        """
        logger.info("🔍 Scanning for SUID binaries (Execute as Root)")

        suid_output = self._executor.remote_execute(
            "find / -perm -u=s -type f 2>/dev/null"
        )

        if suid_output.strip():
            print("\n".join(suid_output.strip().split("\n")))
        else:
            logger.warning("No SUID Binaries Found or Insufficient Permissions.")

        logger.info("🔍 Scanning for SGID binaries (Execute as Group Owner)")

        sgid_output = self._executor.remote_execute(
            "find / -perm -g=s -type f 2>/dev/null"
        )

        if sgid_output.strip():
            print("\n".join(sgid_output.strip().split("\n")))
        else:
            logger.warning("No SGID Binaries Found or Insufficient Permissions.")
