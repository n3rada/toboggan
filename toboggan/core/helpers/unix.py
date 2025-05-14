import secrets
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

    def stealthy_name(
        self,
        prefix_pool: list = None,
        suffix_pool: list = None,
        path_pool: list = None,
        hex_suffix_length: int = 4,
        add_dot_prefix: bool = True,
    ) -> str:

        if prefix_pool is None:
            prefix_pool = [
                "audit",
                "dbus",
                "user",
                "cache",
                "lightdm",
                "gnome",
                "cups",
                "pulse",
                "upower",
                "systemd",
                "snapd",
                "udisksd",
                "at-spi",
                "tracker",
                "gdm",
                "colord",
                "seahorse",
                "ibus",
                "xsession",
                "pam",
                "nm-dispatcher",
                "x11",
                "env",
                "console",
                "mime",
                "session",
                "proc",
            ]

        if suffix_pool is None:
            suffix_pool = [
                "log",
                "out",
                "err",
                "msg",
                "sock",
                "pid",
                "ipc",
                "shm",
                "cache",
                "data",
                "map",
                "tmp",
                "journal",
                "conf",
                "status",
                "dump",
                "db",
                "auth",
                "token",
                "bus",
            ]

        if path_pool is None:
            path_pool = [
                "/dev/shm",
                "/tmp",
                "/var/tmp",
                "/run/lock",
            ]

        # Pick a stealthy directory
        directory = random.choice(path_pool)
        if not directory.endswith("/"):
            directory += "/"

        # Build the name
        prefix = random.choice(prefix_pool)
        suffix = random.choice(suffix_pool)
        hex_id = secrets.token_hex(hex_suffix_length // 2)  # hex digits, so 2 per byte

        name = f"{prefix}-{suffix}-{hex_id}"
        if add_dot_prefix:
            name = f".{name}"

        stealthy_name = f"{directory}{name}"
        self._logger.debug(f"Generated stealthy name: {stealthy_name}")

        return stealthy_name

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
