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
        self.__shell_path = None

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

    def create_alterated_copy_of(
        self, target_binary_name: str, copy_name: str = None
    ) -> str:
        """
        Creates an altered copy of a binary by appending random gibberish characters to avoid detection.

        Args:
            target_binary_name (str): The name of the binary to copy.
            copy_name (str, optional): The name or full path of the copied binary.
                                    If None, generates a random name in the working directory.

        Returns:
            str: The full path of the altered binary.
        """

        # If no copy name is given, generate a random one in the working directory
        if copy_name is None:
            copy_name = utils.generate_fixed_length_token(length=5)
            copied_binary = f"{self._executor.working_directory}/{copy_name}"
        else:
            # If copy_name is a full path, use it directly
            copy_name_path = Path(copy_name)
            if copy_name_path.is_absolute():
                copied_binary = str(copy_name_path)
            else:
                copied_binary = f"{self._executor.working_directory}/{copy_name}"

        # Copy the original binary
        self._executor.remote_execute(
            f"$(command -v cp) $(command -v {target_binary_name}) {copied_binary}"
        )

        allowed_chars = string.ascii_letters + string.digits

        # Generate random gibberish using only allowed characters
        gibberish_length = random.randint(8, 32)
        gibberish = "".join(random.choices(allowed_chars, k=gibberish_length))

        # Append the gibberish to our copy
        self._executor.remote_execute(
            f"$(command -v echo) -n '{gibberish}' >> {copied_binary}"
        )

        self._logger.info(
            f"📀 Created altered binary for '{target_binary_name}': {copied_binary} "
            f"(with {gibberish_length} bytes of gibberish)"
        )

        return copied_binary

    # Properties
    @property
    def shell_path(self) -> str:
        if self.__shell_path is not None:
            return self.__shell_path

        self.__shell_path = self.create_alterated_copy_of(
            "$(ps -p $$ -o comm=)", ".null"
        )
        self._logger.info(f"🐧 Linux shell copied to {self.__shell_path}")

        return self.__shell_path

    @property
    def named_pipe_instance(self) -> NamedPipe:
        return self.__named_pipe_instance
