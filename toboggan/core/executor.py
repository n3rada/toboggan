# Standard library imports
import random
import time
import base64

# Local application/library specific imports
from toboggan.core import logbook
from toboggan.utils.methods import SingletonMeta
from toboggan.core import action
from toboggan.core import target
from toboggan.core.helpers.unix import LinuxHelper
from toboggan.core.helpers.windows import WindowsHelper
from toboggan.core.helpers.base import OSHelperBase


class Executor(metaclass=SingletonMeta):

    def __init__(
        self,
        execute_method: callable = None,
        shell: str = None,
        working_directory: str = None,
        target_os: str = None,
        base64_wrapping: bool = False,
        camouflage: bool = False,
    ):
        self._logger = logbook.get_logger()

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
            self._logger.info(f"🖥️ OS set to {target_os}")

        self._shell = shell
        self._shell_validated = False  # Shell validation flag

        if self.__os not in ["linux", "windows"]:
            raise ValueError("Operating System should be either linux or windows.")

        # Attach the appropriate OS Helper
        if self.__os == "linux":
            self._os_helper = LinuxHelper(self)
        else:
            self._os_helper = WindowsHelper(self)

        self._chunk_max_size = 4096  # Default chunk size for remote commands

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
            user=self.remote_execute(command="whoami").strip(),
            hostname=self.remote_execute(command="hostname").strip(),
            pwd=self._os_helper.get_current_path(),
        )

    # Dunders

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
            if debug:
                self._logger.warning(
                    "⚠️ Attempted to execute an empty command. Skipping."
                )
            return ""

        # Adjust timeout based on avg response time, even if passed explicitly
        if self._avg_response_time is not None and timeout is not None:
            timeout = max(timeout, self._avg_response_time * 1.5)
            if debug:
                self._logger.debug(
                    f"⏱️ Timeout adjusted to {timeout:.2f}s based on avg RTT"
                )

        result = ""

        if debug:
            self._logger.debug(f"Executing: {command}")

        # Apply obfuscation if enabled
        if not bypass_camouflage and self.__camouflage:
            command = self.__camouflage_action.run(command)
            if debug:
                self._logger.debug(f"🔒 Obfuscated command for execution: {command}")

        # Apply Base64 encoding if enabled
        if self.__base64_wrapping:
            command = base64.b64encode(command.encode()).decode()
            if debug:
                self._logger.debug(f"📦 Base64-encoded command: {command}")

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
                    self._logger.success("✅ Remote target is reachable.")

                break  # Exit retry loop on success

            except Exception as exc:

                if self._initial_execution_successful is False:
                    self._logger.error(f"❌ Failed initial execution check: {exc}")
                    raise RuntimeError(
                        "Unable to communicate with remote target. Aborting."
                    )

                if debug:
                    self._logger.warning(
                        f"❌ Execution failed (Attempt {attempt+1}/3): {exc}"
                    )

                if not retry:
                    if debug:
                        self._logger.error(
                            "⏹ Retrying is disabled. Returning empty result."
                        )
                    if raise_on_failure:
                        raise exc

                    return ""

                # Apply exponential backoff with jitter
                sleep_time = (2**attempt) + (random.randint(0, 1000) / 1000)
                if debug:
                    self._logger.warning(
                        f"⏳ Retrying after {sleep_time:.2f} seconds..."
                    )
                time.sleep(sleep_time)

        if not result:
            return ""

        if debug:
            self._logger.debug(f"📩 Received raw output: {result!r}")

        # Attempt to de-obfuscate the result if obfuscation was used
        if not bypass_camouflage and self.__camouflage:
            try:
                result = self.__uncamouflage_action.run(result)
                if debug:
                    self._logger.debug(f"🔓 De-obfuscated output: {result!r}")
            except ValueError:
                if debug:
                    self._logger.error(
                        f"⚠️ Failed to de-obfuscate command output.\n"
                        f"   • Original Command: {command!r}\n"
                        f"   • Received Output: {result!r}"
                    )
                raise

        return result

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
            self._logger.warning(f"⚠️ Failed to delete remote working directory: {exc}")

    def calculate_max_chunk_size(self, min_size=1024, max_size=262144) -> int:
        """
        Determines the maximum shell command size accepted by the remote shell,
        using reverse binary search and ensuring results are multiples of 1024.

        Returns:
            int: Maximum command size in bytes (rounded to nearest 1024) that succeeded.
        """
        self._logger.info(
            "🧪 Starting reverse binary search to determine max command size"
        )
        self._logger.info(
            f"🔢 Search range: {min_size} to {max_size} bytes (1024-aligned)"
        )

        low = (min_size // 1024) * 1024
        high = (max_size // 1024) * 1024
        best = 0

        while low <= high:
            mid = (
                ((low + high) // 2) // 1024 * 1024
            )  # Round mid down to multiple of 1024
            junk_size = mid - len("echo") - 1  # -1 for space
            junk = "A" * junk_size
            cmd = f"echo {junk}"

            self._logger.info(f"📏 Trying command of size: {mid} bytes")

            try:
                self.remote_execute(
                    cmd,
                    timeout=5,
                    retry=False,
                    raise_on_failure=True,
                    debug=False,
                )
                self._logger.info(f"✅ Success at {mid} bytes")
                best = mid
                low = mid + 1024
            except Exception:
                self._logger.info(f"❌ Failure at {mid} bytes")
                high = mid - 1024

            self._logger.debug(
                f"🔁 Updated search range: low={low}, high={high}, best={best}"
            )

        self._logger.success(f"📏 Final max remote command size: {best} bytes")

        return best

    # Private methods

    def __guess_os(self) -> str:
        self._logger.info("🔍 Guessing remote OS")

        if self.remote_execute(command="/bin/ls"):
            self._logger.info("🖥️ Assuming Linux OS.")
            return "linux"

        self._logger.info("🖥️ Assuming Windows OS.")
        return "windows"

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
                else self._os_helper.create_working_directory_string()
            )

            self.remote_execute(command=f"mkdir -p {self._working_directory}")
            self._logger.info(
                f"📂 Remote working directory initialized: {self._working_directory}"
            )

        return self._working_directory

    @property
    def os_helper(self) -> OSHelperBase:
        return self._os_helper

    @property
    def shell(self) -> str:
        # Fallback to dynamic detection if not explicitly set
        if not self._shell:
            if isinstance(self._os_helper, LinuxHelper):
                self._shell = "$(command -v $0)"
            elif isinstance(self._os_helper, WindowsHelper):
                self._shell = "powershell.exe"

        # Validate shell lazily (once)
        if not self._shell_validated:
            self._logger.debug(f"🔍 First-time shell validation (camouflage disabled)")
            test_cmd = f"{self._shell} -h"
            try:
                output = (
                    self.remote_execute(
                        test_cmd,
                        timeout=10,
                        retry=False,
                        debug=True,
                        bypass_camouflage=True,
                    )
                    .strip()
                    .lower()
                )
            except Exception as exc:
                self._logger.warning(f"⚠️ Failed to test shell '{self._shell}': {exc}")
                output = ""

            if not output or "not found" in output or "no such file" in output:
                self._logger.error(f"❌ Remote shell '{self._shell}' appears invalid.")
                raise RuntimeError(f"Shell '{self._shell}' is not usable.")

            self._logger.debug(
                f"💾 Remote shell resolved to: '{self._shell}' — verified and ready."
            )
            self._shell_validated = True

        return self._shell

    @shell.setter
    def shell(self, shell: str) -> None:
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
            self._logger.warning(
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
            self._logger.error(
                f"❌ Chunk size of {size} bytes does not work on the remote system."
            )
            return

        self._chunk_max_size = size
        self._logger.info(f"📏 Chunk max size set to: {self._chunk_max_size} bytes")
