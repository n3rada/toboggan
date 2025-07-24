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
        used_shell = shell if shell else self._executor.os_helper.shell

        self._logger.info(f"🔄 Attempting to upgrade shell to: {used_shell}")

        if script_path := self._executor.remote_execute("command -v script"):
            self._logger.info(f"✅ Found script at: {script_path}")
            self._executor.os_helper.fifo_execute(
                command=f"SHELL={used_shell} script -q /dev/null"
            )
            return

        if expect_path := self._executor.remote_execute("command -v expect"):
            self._logger.info(f"✅ Found expect at: {expect_path}")
            self._executor.os_helper.fifo_execute(
                command=f"expect -c 'spawn {used_shell}; interact'"
            )
            return

        if python_path := self._executor.remote_execute("command -v python3"):
            self._logger.info(f"✅ Found Python3 at: {python_path}")
            random_word = RandomWord().word(word_min_length=4)
            self._executor.os_helper.fifo_execute(
                command=f"{python_path} -c 'import os,pty,signal; [signal.signal({random_word}, signal.SIG_DFL) for {random_word} in (signal.SIGTTOU, signal.SIGTTIN, signal.SIGTSTP)]; pty.spawn(\"{used_shell}\")'"
            )
            return

        self._logger.warning("⚠️ No suitable method found for upgrading the shell.")
