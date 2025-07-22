# Standard library imports
import random
import time
import base64

# Local application/library specific imports
from toboggan.core import logbook
from toboggan.core.utils import SingletonMeta
from toboggan.core import action
from toboggan.core import target
from toboggan.core.helpers.unix import UnixHelper
from toboggan.core.helpers.windows import WindowsHelper
from toboggan.core.helpers.base import OSHelperBase


class Executor(metaclass=SingletonMeta):

    def __init__(
        self,
        execute_method: callable = None,
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

        if target_os is None:
            self.__os = self.__guess_os()
        else:
            self.__os = target_os
            self._logger.info(f"🖥️ OS set to {target_os}")

        if self.__os not in ["unix", "windows"]:
            raise ValueError("Operating System should be either unix or windows.")

        # Attach the appropriate OS Helper
        if self.__os == "unix":
            self._os_helper = UnixHelper(self)
        elif self.__os == "windows":
            self._os_helper = WindowsHelper(self)

        self.__action_manager = action.ActionsManager(target_os=self.__os)

        self._provided_working_directory = working_directory
        self._working_directory = None

        self._initial_execution_successful = (
            False  # Will become True only if remote is reachable
        )

        self._avg_response_time = None  # Exponential moving average
        self._response_alpha = 0.4  # Weight of most recent observation (adjustable)

        if camouflage:
            self.__camouflage_action = self.__action_manager.get_action("camouflage")(
                executor=self
            )
            self.__uncamouflage_action = self.__action_manager.get_action(
                "uncamouflage"
            )(executor=self)
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
        debug: bool = True,
    ) -> str:
        """
        Executes the specified command within the module.

        Args:
            command (str): Command to be executed remotely.
            timeout (float, optional): Timeout for command execution.
            retry (bool, optional): Whether to retry on failure.
            debug (bool, optional): Enable or disable debug logging for this execution.

        Returns:
            str: The output of the executed command, if successful.
        """

        if not command:
            if debug:
                self._logger.warning(
                    "⚠️ Attempted to execute an empty command. Skipping."
                )
            return ""

        result = ""

        if debug:
            self._logger.debug(f"Executing: {command}")

        # Apply obfuscation if enabled
        if self.__camouflage:
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
                    self._logger.success(
                        "✅ Initial command execution successful. Remote target is reachable."
                    )

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
        if self.__camouflage:
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

    # Private methods

    def __guess_os(self) -> str:
        self._logger.info("🔍 Guessing remote OS")

        if self.remote_execute(command="/bin/ls"):
            self._logger.info("🖥️ Assuming Unix-like OS.")
            return "unix"

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
    def is_ready(self) -> bool:
        return self._initial_execution_successful

    @property
    def avg_response_time(self) -> float | None:
        """Rolling average of response time for remote commands."""
        return self._avg_response_time
