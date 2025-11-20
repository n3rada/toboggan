# Standard library imports
import random
import time
import base64

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.src.utils.common import SingletonMeta
from toboggan.src import action
from toboggan.src import target
from toboggan.src.helpers.linux import LinuxHelper
from toboggan.src.helpers.windows import WindowsHelper
from toboggan.src.helpers.base import OSHelperBase


class Executor(metaclass=SingletonMeta):

    def __init__(
        self,
        execute_method: callable = None,
        shell: str = None,
        working_directory: str = None,
        target_os: str = None,
        base64_wrapping: bool = False,
        camouflage: bool = False,
        custom_paths: list = None,
    ):
        if execute_method is None:
            raise ValueError("Executor should have an execute callable method.")

        self.__execute = execute_method
        self.__base64_wrapping = base64_wrapping
        self.__camouflage = False

        self._initial_execution_successful = (
            False  # Will become True only if remote is reachable
        )

        self._avg_response_time = None  # Exponential moving average
        self._response_alpha = 0.4  # Weight of most recent observation (adjustable)

        if target_os is None:
            self.__os = self.__guess_os()
        else:
            self.__os = target_os
            logger.info(f"🖥️ OS set to {target_os}")

        self._shell = shell
        self._shell_validated = False  # Shell validation flag

        if self.__os not in ["linux", "windows"]:
            raise ValueError("Operating System should be either linux or windows.")

        # Attach the appropriate OS Helper
        if self.__os == "linux":
            self._os_helper = LinuxHelper(self, custom_paths=custom_paths)
        else:
            self._os_helper = WindowsHelper(self)

        self._chunk_max_size = 2048  # Default chunk size for remote commands

        self.__action_manager = action.ActionsManager(target_os=self.__os)

        self._provided_working_directory = working_directory
        self._working_directory = None

        if camouflage:
            self.__camouflage_action = self.__action_manager.get_action("hide")(
                executor=self
            )
            self.__uncamouflage_action = self.__action_manager.get_action("unhide")(
                executor=self
            )
            self.__camouflage = True

        self.__target = target.Target(
            os=self.__os,
            user=self._os_helper.get_current_user(),
            hostname=self._os_helper.get_hostname(),
            pwd=self._os_helper.get_current_path(),
        )

    # Dunders

    # Properties
    @property
    def target(self) -> target.Target:
        return self.__target

    @property
    def action_manager(self) -> action.ActionsManager:
        return self.__action_manager

    @property
    def has_working_directory(self) -> bool:
        return (
            hasattr(self, "_working_directory") and self._working_directory is not None
        )

    @property
    def working_directory(self) -> str:
        """
        Lazily initializes and returns the working directory.
        Creates the remote directory only when accessed the first time.
        """
        if not self.has_working_directory:
            self._working_directory = (
                self._provided_working_directory
                if (
                    hasattr(self, "_provided_working_directory")
                    and self._provided_working_directory is not None
                )
                else self._os_helper.format_working_directory()
            )

            self.remote_execute(command=f"mkdir -p {self._working_directory}")
            logger.info(
                f"📂 Remote working directory initialized: {self._working_directory}"
            )

        return self._working_directory

    @property
    def os_helper(self) -> OSHelperBase:
        return self._os_helper

    @property
    def shell(self) -> str:
        """
        Returns the current shell to be used for remote command execution.

        This property determines and validates the appropriate shell for the remote target,
        depending on the operating system. For Linux targets, it tries a list of common shells
        in order, falling back if validation fails. For Windows, it defaults to PowerShell.

        The shell is validated by attempting to locate it on the
        remote system.

        Raises:
            RuntimeError: If no valid shell can be found or validated on a Linux target.

        Returns:
            str: The name of the validated shell to use for remote execution.
        """

        linux_shells = ["$0", "zsh", "bash", "sh"]

        if not self._shell:
            if isinstance(self._os_helper, LinuxHelper):
                # Try first one
                self.shell = linux_shells.pop(0)

            elif isinstance(self._os_helper, WindowsHelper):
                self.shell = "powershell"
                self._shell_validated = True  # Assume PowerShell is valid

        while not self._shell_validated:

            if not self.__validate_shell():
                if isinstance(self._os_helper, LinuxHelper):
                    if linux_shells:
                        next_shell = linux_shells.pop(0)
                        logger.info(f"🔄 Falling back to {next_shell}")
                        self.shell = next_shell
                        continue
                    else:
                        logger.error("❌ No valid shell found on Linux target.")
                        raise RuntimeError("No valid shell found on Linux target.")

        return self._shell

    @shell.setter
    def shell(self, shell: str) -> None:
        """
        Sets the shell to be used for remote command execution.

        This setter updates the shell used by the Executor for running remote commands.
        It also resets the shell validation flag, so the next access to the shell property
        will trigger validation of the new shell.

        Args:
            shell (str): The name or path of the shell to use for remote execution (e.g., 'bash', 'zsh', 'powershell').
        """
        self._shell = shell
        self._shell_validated = False  # Reset validation flag

    @property
    def is_ready(self) -> bool:
        return self._initial_execution_successful

    @property
    def avg_response_time(self) -> float | None:
        """Rolling average of response time for remote commands."""
        return self._avg_response_time

    @property
    def chunk_max_size(self) -> int:
        """Maximum size of a chunk for remote command execution."""
        return self._chunk_max_size

    @chunk_max_size.setter
    def chunk_max_size(self, size: int) -> None:
        """Set the maximum size of a chunk for remote command execution."""
        if size <= 0:
            raise ValueError("Chunk size must be a positive integer.")

        if size % 1024 != 0:
            logger.warning(
                f"Chunk size {size} is not a multiple of 1024. Rounding down to nearest 1024."
            )
            size = (size // 1024) * 1024

        try:
            self.remote_execute(
                f"echo {'A' * (size - len('echo') - 1)}",
                # -1 for space
                timeout=5,
                retry=False,
                raise_on_failure=True,
                debug=False,
            )
        except Exception:
            logger.error(
                f"❌ Chunk size of {size} bytes does not work on the remote system."
            )
            return

        self._chunk_max_size = size
        logger.info(f"📏 Chunk max size set to: {self._chunk_max_size} bytes")

    # Public methods

    def one_shot_execute(self, command: str = None, debug: bool = False) -> None:
        """Execute a command without returning nothing and with a fast timeout.

        Args:
            command (str): Command to be executed.
        """
        try:
            self.remote_execute(command=command, timeout=3, retry=False, debug=debug)
        except Exception:
            return

    def remote_execute(
        self,
        command: str,
        timeout: float = None,
        retry: bool = True,
        raise_on_failure: bool = False,
        debug: bool = True,
        bypass_camouflage: bool = False,
    ) -> str:
        """
        Executes the specified command within the module.

        Args:
            command (str): Command to be executed remotely.
            timeout (float, optional): Timeout for command execution.
            retry (bool, optional): Whether to retry on failure.
            debug (bool, optional): Enable or disable debug logging for this execution.
            bypass_camouflage (bool, optional): Bypass camouflage check.

        Returns:
            str: The output of the executed command, if successful.
        """

        if not command:
            logger.trace("⚠️ Attempted to execute an empty command. Skipping.")
            return ""

        if debug:
            logger.debug(f"Executing: {command}")

        # Adjust timeout based on avg response time, even if passed explicitly
        if self._avg_response_time is not None and timeout is not None:
            timeout = max(timeout, self._avg_response_time * 1.5)
            if debug:
                logger.debug(f"⏱️ Timeout adjusted to {timeout:.2f}s based on avg RTT")

        result = ""

        # Apply obfuscation if enabled
        if not bypass_camouflage and self.__camouflage:
            command = self.__camouflage_action.run(command)
            logger.trace(f"🔒 Obfuscated command for execution: {command}")

        # Apply Base64 encoding if enabled
        if self.__base64_wrapping:
            command = base64.b64encode(command.encode()).decode()
            logger.trace(f"📦 Base64-encoded command: {command}")

        for attempt in range(3):
            try:
                start_time = time.time()
                result = self.__execute(command=command, timeout=timeout)
                end_time = time.time()

                # Update response time average
                elapsed = end_time - start_time
                if self._avg_response_time is None:
                    self._avg_response_time = elapsed
                else:
                    self._avg_response_time = (
                        self._response_alpha * elapsed
                        + (1 - self._response_alpha) * self._avg_response_time
                    )

                if self._initial_execution_successful is False:
                    self._initial_execution_successful = True
                    logger.success("✅ Remote target is reachable.")

                break  # Exit retry loop on success

            except Exception as exc:

                if self._initial_execution_successful is False:
                    logger.error(f"❌ Failed initial execution check: {exc}")
                    raise RuntimeError(
                        "Unable to communicate with remote target. Aborting."
                    )

                if debug:
                    logger.warning(
                        f"❌ Execution failed (Attempt {attempt+1}/3): {exc}"
                    )

                if not retry:
                    if debug:
                        logger.error("⏹ Retrying is disabled. Returning empty result.")
                    if raise_on_failure:
                        raise exc

                    return ""

                # Apply exponential backoff with jitter
                sleep_time = (2**attempt) + (random.randint(0, 1000) / 1000)
                if debug:
                    logger.warning(f"⏳ Retrying after {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)

        if not result:
            return ""

        logger.trace(f"📩 Received raw output: {result!r}")

        # Attempt to de-obfuscate the result if obfuscation was used
        if not bypass_camouflage and self.__camouflage:
            try:
                result = self.__uncamouflage_action.run(result)
                logger.trace(f"🔓 De-obfuscated output: {result!r}")
            except ValueError:
                if debug:
                    logger.error(
                        f"⚠️ Failed to de-obfuscate command output.\n"
                        f"   • Original Command: {command!r}\n"
                        f"   • Received Output: {result!r}"
                    )
                raise

        return str(result)

    def delete_working_directory(self) -> None:
        """
        Deletes the remote working directory if it has been created.

        Args:
            debug (bool): Whether to log deletion info.
        """
        if not self.has_working_directory:
            return
        try:
            self.remote_execute(f"rm -r {self._working_directory}")
        except Exception as exc:
            logger.warning(f"⚠️ Failed to delete remote working directory: {exc}")

    def calculate_max_chunk_size(self, min_size=1024, max_size=262144) -> int:
        """
        Determines the maximum shell command size accepted by the remote shell.
        First tries the maximum size directly, then falls back to binary search if needed.
        All sizes are ensured to be multiples of 1024.

        Returns:
            int: Maximum command size in bytes (rounded to nearest 1024) that succeeded.
        """
        # Round max_size down to nearest multiple of 1024
        max_size = (max_size // 1024) * 1024
        min_size = (min_size // 1024) * 1024

        # Try maximum size first
        junk_size = max_size - len("echo") - 1  # -1 for space
        junk = "A" * junk_size
        cmd = f"echo {junk}"

        logger.info(f"📏 Trying maximum size: {max_size} bytes")

        try:
            self.remote_execute(
                cmd,
                timeout=5,
                retry=False,
                raise_on_failure=True,
                debug=False,
            )
            logger.success(f"✅ Maximum size {max_size} bytes works!")
            return max_size
        except Exception:
            logger.info("❌ Maximum size failed, falling back to binary search")

        # Fall back to binary search if maximum size failed
        logger.info(
            f"🔢 Binary search range: {min_size} to {max_size} bytes (1024-aligned)"
        )

        low = min_size
        high = max_size
        best = 0

        while low <= high:
            mid = ((low + high) // 2) // 1024 * 1024  # Round to multiple of 1024
            junk_size = mid - len("echo") - 1  # -1 for space
            junk = "A" * junk_size
            cmd = f"echo {junk}"

            logger.info(f"📏 Trying size: {mid} bytes")

            try:
                self.remote_execute(
                    cmd,
                    timeout=5,
                    retry=False,
                    raise_on_failure=True,
                    debug=False,
                )
                logger.info(f"✅ Success at {mid} bytes")
                best = mid
                low = mid + 1024
            except Exception:
                logger.info(f"❌ Failed at {mid} bytes")
                high = mid - 1024

            logger.debug(f"🔁 Search range: low={low}, high={high}, best={best}")

        logger.success(f"📏 Final maximum command size: {best} bytes")
        return best

    # Private methods

    def __guess_os(self) -> str:
        logger.info("🔍 Guessing remote OS")

        uname_output = self.remote_execute(command="uname", retry=False).strip().lower()

        if uname_output and "not recognized" not in uname_output:
            logger.info("🖥️ Detected Linux OS via uname.")
            return "linux"

        logger.info("🖥️ Assuming Windows OS.")
        return "windows"

    def __validate_shell(self) -> bool:
        """
        Validates the current shell for remote command execution.

        Attempts multiple validation methods for maximum compatibility:
        1. command -v (POSIX)
        2. which (common but not POSIX)
        3. type (built-in, very portable)

        Returns:
            bool: True if the shell is valid and available on the remote system, False otherwise.
        """
        if isinstance(self._os_helper, WindowsHelper):
            return True  # Assume PowerShell is valid for Windows

        # Try multiple validation methods in order of preference
        validation_commands = [
            f"command -v {self._shell}",  # POSIX standard
            f"which {self._shell} 2>/dev/null",  # Common utility
            f"type {self._shell} 2>/dev/null",  # Shell built-in
        ]

        for validation_command in validation_commands:
            try:
                output = (
                    self.remote_execute(
                        validation_command,
                        timeout=10,
                        retry=False,
                        debug=False,
                        bypass_camouflage=True,
                    )
                    .strip()
                    .lower()
                )

                if (
                    output
                    and "not found" not in output
                    and "no such file" not in output
                ):
                    logger.debug(
                        f"✅ Shell validation succeeded with: {validation_command}"
                    )
                    logger.info(
                        f"💾 Remote shell: '{self._shell}' — verified and ready."
                    )
                    self._shell_validated = True
                    return True

            except Exception:
                continue  # Try next validation method

        logger.error(f"❌ Remote shell '{self._shell}' could not be validated.")
        self._shell_validated = False
        return False
