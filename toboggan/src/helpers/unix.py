import secrets
import random
import re

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.src.helpers import base
from toboggan.src.utils import common
from toboggan.src.action import NamedPipe


class LinuxHelper(base.OSHelperBase):
    """
    Unix-specific operations like handling binaries and shell paths.
    """

    def __init__(self, executor):
        super().__init__(executor)
        self.__named_pipe_instance = None

        self.__is_busybox_present = None
        self.__busybox_commands = set()

        logger.debug("Initialized LinuxHelper.")

    def fifo_execute(self, command: str) -> None:
        self.__named_pipe_instance.execute(command)

    def start_named_pipe(self, action_class, **kwargs) -> None:
        """Starts a NamedPipe action and keeps track of it."""
        if not issubclass(action_class, NamedPipe):
            logger.error(f"❌ {action_class.__name__} is not a NamedPipe action.")
            return

        try:
            self.__named_pipe_instance = action_class(self._executor, **kwargs)
            self.__named_pipe_instance.setup()
            self.__named_pipe_instance.run()
            logger.success(f"✅ Named pipe {action_class.__name__} started!")

        except Exception as e:
            logger.error(f"⚠️ Failed to start named pipe: {e}")
            self.__named_pipe_instance = None

    def stop_named_pipe(self):
        """Stops the named pipe session if active."""
        if self.__named_pipe_instance:
            self.__named_pipe_instance.stop()
            self.__named_pipe_instance = None

    def is_fifo_active(self) -> bool:
        """Returns True if a FIFO session is active."""
        return self.__named_pipe_instance is not None

    def format_working_directory(self) -> str:
        """Generate a temp directory path."""

        random_hex = common.generate_fixed_length_token(length=32)
        random_suffix = common.generate_fixed_length_token(length=6).upper()
        return f"/tmp/systemd-private-{random_hex}-upower.service-{random_suffix}"

    def random_system_file_name(
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

        random_system_file_name = f"{directory}{name}"
        logger.debug(f"Generated random system file name: {random_system_file_name}")

        return random_system_file_name

    def get_current_path(self) -> str:
        return self._executor.remote_execute(command="pwd").strip()

    def is_shell_prompt_in(self, stdout_pathput: str) -> bool:
        """
        Detects if the command output is a shell prompt.

        Args:
            stdout_pathput (str): The latest command output to analyze.

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

        return any(re.search(pattern, stdout_pathput) for pattern in prompt_patterns)

    def check_busybox(self) -> bool:
        """
        Checks if BusyBox is present and loads its available commands into a set.
        Returns:
            bool: True if BusyBox is found, False otherwise.
        """
        logger.info("🔍 Checking for BusyBox presence on the target system.")
        try:
            result = self._executor.remote_execute(command="/bin/busybox", debug=False)

            if result and "Currently defined functions:" in result:
                self.__is_busybox_present = True
                self.__busybox_commands = self.__parse_busybox_commands(result)
                logger.success("📦 BusyBox detected and command list parsed.")
                return True

            logger.warning("⚠️ BusyBox not found or output not recognized.")
            self.__is_busybox_present = False
            return False
        except Exception as exc:
            logger.error(f"❌ Error while checking BusyBox: {exc}")
            return False

    def __parse_busybox_commands(self, output: str) -> set[str]:
        """
        Parses the output of `busybox --help` to extract available command names.

        Args:
            output (str): The stdout string from BusyBox.

        Returns:
            set[str]: Set of supported BusyBox function names.
        """
        collecting = False
        commands = set()

        for line in output.strip().splitlines():
            if "Currently defined functions:" in line:
                collecting = True
                continue

            if collecting:
                words = line.strip().split()
                for word in words:
                    commands.add(word.rstrip(","))

        return commands

    def busybox_wrap(self, full_command: str) -> str:
        """
        Wrap a full command with /bin/busybox if its base command is supported.
        Args:
            full_command (str): A complete shell command, e.g., "ls -la /tmp"
        Returns:
            str: Wrapped command using busybox or fallback with command -v
        """
        if not self.__is_busybox_present:
            return full_command

        parts = full_command.strip().split()
        if not parts:
            return full_command

        base_cmd = parts[0]
        if base_cmd in self.__busybox_commands:
            return f"/bin/busybox {full_command}"

        return f"$(command -v {base_cmd}) {' '.join(parts[1:])}"

    # Properties

    @property
    def named_pipe_instance(self) -> NamedPipe:
        return self.__named_pipe_instance

    @property
    def busybox_commands(self) -> set:
        return self.__busybox_commands

    @property
    def is_busybox_present(self) -> bool:
        if self.__is_busybox_present is None:
            self.__is_busybox_present = self.check_busybox()

        return self.__is_busybox_present
