import secrets
import random
import re

# External library imports
from loguru import logger

# Local application/library specific imports
from . import base
from ..utils import common
from .core.action import NamedPipe


class LinuxHelper(base.OSHelperBase):
    """
    Unix-specific operations like handling binaries and shell paths.
    """

    def __init__(self, executor, custom_paths: list = None):
        super().__init__(executor)
        self.__named_pipe_instance = None

        self.__is_busybox_present = None
        self.__busybox_commands = set()

        self.__detection_method = None

        # Cache for command locations to avoid redundant lookups
        self.__command_location_cache = {}

        # Custom paths to check first before using standard detection methods
        self.__custom_paths = custom_paths or []

        if self.__custom_paths:
            logger.info(
                f"📂 Custom command paths configured: {', '.join(self.__custom_paths)}"
            )

        logger.trace("Initialized LinuxHelper.")

    def get_current_user(self):
        whoami_path = self.get_command_location("whoami")
        return self._executor.remote_execute(command=whoami_path).strip()

    def get_hostname(self) -> str:
        return self._executor.remote_execute(command="hostname").strip()

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

    def get_command_location(self, command: str) -> str:
        """
        Retrieves the full path of a command using multiple detection methods.

        Tries multiple methods for maximum compatibility across different Unix-like systems:
        1. Custom paths (if provided via --paths)
        2. busybox wrap (if applicable)
        3. command -v (POSIX standard)
        4. which (common utility)
        5. type (shell built-in)

        This ensures compatibility with:
        - Standard Linux/Unix systems
        - BusyBox environments
        - IBM i (AS/400) QShell
        - Minimal POSIX shells

        Args:
            command: The command to locate.

        Returns:
            str: The full path of the command if found, else an empty string.
        """

        # Check cache first
        if command in self.__command_location_cache:
            logger.trace(
                f"💾 Command location retrieved from cache: {command} -> {self.__command_location_cache[command]}"
            )
            return self.__command_location_cache[command]

        # Try custom paths first if provided
        if self.__custom_paths:
            for custom_path in self.__custom_paths:
                # Ensure path ends with /
                if not custom_path.endswith("/"):
                    custom_path += "/"

                full_path = f"{custom_path}{command}"

                # Check if the command exists at this custom path
                try:
                    check_result = self._executor.remote_execute(
                        f"test -x {full_path} && echo E", debug=False
                    ).strip()

                    if check_result == "E":
                        self.__command_location_cache[command] = full_path
                        logger.trace(
                            f"💾 Cached command from custom path: {command} -> {full_path}"
                        )
                        return full_path
                except Exception:
                    continue  # Try next custom path

        # Wrap a full command with /bin/busybox if its base command is supported.
        if self.__is_busybox_present:
            if command in self.__busybox_commands:
                location = f"/bin/busybox {command}"
                self.__command_location_cache[command] = location
                logger.trace(f"💾 Cached busybox command: {command} -> {location}")
                return location

        # Try the previously successful detection method first
        if self.__detection_method is not None:
            result = self._executor.remote_execute(
                f"{self.__detection_method} {command}", debug=False
            ).strip()

            if result and "not found" not in result.lower():
                self.__command_location_cache[command] = result
                logger.trace(f"💾 Cached command location: {command} -> {result}")
                return result

        # Try multiple detection methods in order of preference
        detection_methods = [
            "command -v",  # POSIX standard
            "which",
            "type",
            "whence",
        ]

        # Remove the previously tried method if any
        if self.__detection_method in detection_methods:
            detection_methods.remove(self.__detection_method)

        wrong_detection_words = ["not found", "pas de", f"{command}:"]

        for method in detection_methods:
            try:
                location = self._executor.remote_execute(
                    f"{method}  {command}", debug=False
                ).strip()

                # Clean up output (some methods return extra text)
                if location and not any(
                    word in location.lower() for word in wrong_detection_words
                ):
                    # Extract just the path if there's extra text
                    # Example: "bash is /bin/bash" -> "/bin/bash"
                    if " " in location:
                        parts = location.split()
                        for part in parts:
                            if part.startswith("/"):
                                location = part
                                break

                    # Validate it's an actual path
                    if location.startswith("/"):
                        self.__detection_method = method
                        logger.info(
                            f"🔎 Working detection method found: {self.__detection_method}"
                        )
                        self.__command_location_cache[command] = location
                        logger.trace(
                            f"💾 Cached command location: {command} -> {location}"
                        )
                        return location

            except Exception:
                continue  # Try next method

        logger.warning(f"No detection method worked for command: {command}")
        # Cache empty result to avoid repeated failed lookups
        self.__command_location_cache[command] = ""
        return ""

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

    @property
    def command_location_cache(self) -> dict:
        """Returns the command location cache dictionary."""
        return self.__command_location_cache

    def clear_command_cache(self, command: str = None) -> None:
        """
        Clears the command location cache.

        Args:
            command: If provided, clears only this command from cache.
                    If None, clears the entire cache.
        """
        if command:
            if command in self.__command_location_cache:
                del self.__command_location_cache[command]
                logger.debug(f"🗑️ Cleared cache for command: {command}")
        else:
            self.__command_location_cache.clear()
            logger.debug("🗑️ Cleared entire command location cache")
