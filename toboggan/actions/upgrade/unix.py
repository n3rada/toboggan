# Third-party imports
from wonderwords import RandomWord

# Local application/library specific imports
from toboggan.core.action import BaseAction


class UpgradeAction(BaseAction):
    DESCRIPTION = "Attempts to upgrade a limited shell to a TTY."

    def run(self, shell: str = None) -> None:
        """
        Upgrade a limited shell to a fully interactive TTY.

        Args:
            shell (Optional[str]): The shell to upgrade to (e.g., /bin/bash). Defaults to the OS helper's shell.
        """

        if not self._executor.os_helper.is_fifo_active():
            self._logger.error("❌ Upgrade requires a FIFO session. Start one first!")
            return

        # Use provided shell or fallback to default
        shell_path = shell if shell else self._executor.os_helper.shell_path

        self._logger.info(f"🔄 Attempting to upgrade shell to: {shell_path}")

        if script_path := self._executor.remote_execute("command -v script"):
            self._logger.info(f"✅ Found script at: {script_path}")
            self._executor.os_helper.fifo_execute(
                command=f"SHELL={shell_path} script -q /dev/null"
            )
            return

        if expect_path := self._executor.remote_execute("command -v expect"):
            self._logger.info(f"✅ Found expect at: {expect_path}")
            self._executor.os_helper.fifo_execute(
                command=f"expect -c 'spawn {shell_path}; interact'"
            )
            return

        if python_path := self._executor.remote_execute("command -v python3"):
            self._logger.info(f"✅ Found Python3 at: {python_path}")
            random_word = RandomWord().word(word_min_length=4)
            self._executor.os_helper.fifo_execute(
                command=f"{python_path} -c 'import os,pty,signal; [signal.signal({random_word}, signal.SIG_DFL) for {random_word} in (signal.SIGTTOU, signal.SIGTTIN, signal.SIGTSTP)]; pty.spawn(\"{shell_path}\")'"
            )
            return

        self._logger.warning("⚠️ No suitable method found for upgrading the shell.")
