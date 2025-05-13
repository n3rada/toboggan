from pathlib import Path
import string
import random
import re

from toboggan.core.helpers import base
from toboggan.core import utils
from toboggan.core.action import NamedPipe


class UnixHelper(base.OSHelperBase):
    """
    Unix-specific operations like handling binaries and shell paths.
    """

    def __init__(self, executor):
        super().__init__(executor)
        self.__shell_path = "/bin/bash"

        self.__named_pipe_instance = None

    def fifo_execute(self, command: str) -> None:
        self.__named_pipe_instance.execute(command)

    def start_named_pipe(self, action_class, **kwargs):
        """Starts a NamedPipe action and keeps track of it."""
        if not issubclass(action_class, NamedPipe):
            self._logger.error(f"❌ {action_class.__name__} is not a NamedPipe action.")
            return

        try:
            self.__named_pipe_instance = action_class(self._executor, **kwargs)
            self.__named_pipe_instance.setup()
            self.__named_pipe_instance.run()
            self._logger.success(f"✅ Named pipe {action_class.__name__} started!")

        except Exception as e:
            self._logger.error(f"⚠️ Failed to start named pipe: {e}")
            self.__named_pipe_instance = None

    def stop_named_pipe(self):
        """Stops the named pipe session if active."""
        if self.__named_pipe_instance:
            self.__named_pipe_instance.stop()
            self.__named_pipe_instance = None

    def is_fifo_active(self) -> bool:
        """Returns True if a FIFO session is active."""
        return self.__named_pipe_instance is not None

    def create_working_directory_string(self) -> str:
        """Generate a temp directory path."""

        random_hex = utils.generate_fixed_length_token(length=32)
        random_suffix = utils.generate_fixed_length_token(length=6).upper()
        return f"/tmp/systemd-private-{random_hex}-upower.service-{random_suffix}"

    def get_current_path(self) -> str:
        return self._executor.remote_execute(command="/bin/pwd").strip()

    def is_shell_prompt_in(self, command_output: str) -> bool:
        """
        Detects if the command output is a shell prompt.

        Args:
            command_output (str): The latest command output to analyze.

        Returns:
            bool: True if the output appears to be a shell prompt, False otherwise.
        """
        prompt_patterns = [
            r"\$\s*$",  # Standard user bash-like prompt
            r"#\s*$",  # Root shell prompt
            r".*@.*:.*\$",  # user@host:/path$ (common for interactive shells)
            r"┌──\((.*?)㉿(.*?)\)-\[.*\]",  # Kali-specific prompt: ┌──(user㉿hostname)-[path]
            r"root@.*?:.*?#",  # Generic root prompt
        ]

        return any(re.search(pattern, command_output) for pattern in prompt_patterns)

    # Properties
    @property
    def shell_path(self) -> str:
        return self.__shell_path

    @property
    def named_pipe_instance(self) -> NamedPipe:
        return self.__named_pipe_instance
