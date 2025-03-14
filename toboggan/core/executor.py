# Standard library imports
import random
import string
import time
import base64

# Local application/library specific imports
from toboggan.core import logbook
from toboggan.core.utils import SingletonMeta
from toboggan.core import action
from toboggan.core import target
from toboggan.core import utils


class Executor(metaclass=SingletonMeta):

    def __init__(
        self,
        execute_method: callable = None,
        working_directory: str = None,
        target_os: str = None,
        base64_wrapping: bool = False,
        hide: bool = False,
    ):
        self.__logger = logbook.get_logger()

        if execute_method is None:
            raise ValueError(
                "Executor should have an execute callable method passed as argument"
            )

        self.__execute = execute_method

        self.__base64_wrapping = base64_wrapping

        self.__hide = None

        if target_os is None:
            self.__os = self.__guess_os()
        else:
            self.__os = target_os
            self.__logger.info(f"🖥️ OS set to {target_os}")

        if self.__os not in ["unix", "windows"]:
            raise ValueError("Operating System should be either unix or windows.")

        # Cache hide/unhide action instances
        self.__hide = hide

        self.__action_manager = action.ActionsManager(target_os=self.__os)

        if hide:
            self.__hide_action = self.__action_manager.get_action("hide")(executor=self)
            self.__unhide_action = self.__action_manager.get_action("unhide")(
                executor=self
            )

        self.__target = target.Target(
            os=self.__os,
            user=self.remote_execute(command="whoami").strip(),
            hostname=self.remote_execute(command="hostname").strip(),
            pwd=self.__get_current_path(),
        )

        if working_directory is None:
            self._working_directory = self._create_working_directory_string()
        else:
            self._working_directory = working_directory

        self.remote_execute(command=f"mkdir {self._working_directory}")

        self.__logger.info(f"📂 Remote working directory: {self._working_directory}")

    # Dunders

    # Public methods

    def one_shot_execute(self, command: str = None, debug: bool = False) -> None:
        """Execute a command without returning nothing and with a fast timeout.

        Args:
            command (str): Command to be executed.
        """
        try:
            self.remote_execute(command=command, timeout=1, retry=False, debug=debug)
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
                self.__logger.warning(
                    "⚠️ Attempted to execute an empty command. Skipping."
                )
            return ""

        result = ""

        if debug:
            self.__logger.debug(f"Executing: {command}")

        # Apply obfuscation if enabled
        if self.__hide:
            command = self.__hide_action.run(command)
            if debug:
                self.__logger.debug(f"🔒 Obfuscated command for execution: {command}")

        # Apply Base64 encoding if enabled
        if self.__base64_wrapping:
            command = base64.b64encode(command.encode()).decode()
            if debug:
                self.__logger.debug(f"📦 Base64-encoded command: {command}")

        for attempt in range(3):
            try:
                result = self.__execute(command=command, timeout=timeout)
                break  # Exit retry loop on success

            except Exception as exc:
                if debug:
                    self.__logger.warning(
                        f"❌ Execution failed (Attempt {attempt+1}/3): {exc}"
                    )

                if not retry:
                    if debug:
                        self.__logger.error(
                            "⏹ Retrying is disabled. Returning empty result."
                        )
                    return ""

                # Apply exponential backoff with jitter
                sleep_time = (2**attempt) + (random.randint(0, 1000) / 1000)
                if debug:
                    self.__logger.warning(
                        f"⏳ Retrying after {sleep_time:.2f} seconds..."
                    )
                time.sleep(sleep_time)

        if not result:
            return ""

        if debug:
            self.__logger.debug(f"📩 Received raw output: {result!r}")

        # Attempt to de-obfuscate the result if obfuscation was used
        if self.__hide:
            try:
                result = self.__unhide_action.run(result)
                if debug:
                    self.__logger.debug(f"🔓 De-obfuscated output: {result!r}")
            except ValueError:
                if debug:
                    self.__logger.error(
                        f"⚠️ Failed to de-obfuscate command output.\n"
                        f"   • Original Command: {command!r}\n"
                        f"   • Received Output: {result!r}"
                    )
                raise

        return result

    def create_alterated_copy_of(
        self, target_binary_name: str, copy_name: str = None
    ) -> str:
        """
        Creates an altered copy of a binary by appending random gibberish characters to avoid detection.

        Args:
            target_binary_name (str): The name of the binary to copy.
            copy_name (str, optional): The name of the copied binary. If None, generates a random name.

        Returns:
            str: The full path of the altered binary.
        """
        if copy_name is None:
            copy_name = utils.generate_fixed_length_token(length=5)

        copied_binary = f"{self.working_directory}/{copy_name}"

        # Copy the original binary
        self.remote_execute(
            f"$(command -v cp) $(command -v {target_binary_name}) {copied_binary}"
        )

        # Define allowed gibberish characters (printable, but no spaces, newlines, or control chars)
        allowed_chars = "".join(
            c for c in string.printable if c.isalnum() or c in string.punctuation
        )

        # Generate random gibberish using only allowed characters
        gibberish_length = random.randint(8, 32)
        gibberish = "".join(random.choices(allowed_chars, k=gibberish_length))

        # Append the gibberish to our copy
        self.remote_execute(f"$(command -v echo) -n '{gibberish}' >> {copied_binary}")

        self.__logger.info(
            f"📀 Created altered binary for '{target_binary_name}': {copied_binary} (with {gibberish_length} bytes of gibberish)"
        )

        return copied_binary

    # Private methods
    def __get_current_path(self) -> str:
        if self.__os == "unix":
            return self.remote_execute(command="/bin/pwd").strip()

        return self.remote_execute(command="(Get-Location).Path").strip()

    def __guess_os(self) -> str:
        self.__logger.info("🔍 Guessing remote OS")

        if self.remote_execute(command="/bin/ls"):
            self.__logger.info("🖥️ Assuming Unix-like OS.")
            return "unix"

        self.__logger.info("🖥️ Assuming Windows OS.")
        return "windows"

    def _create_working_directory_string(self) -> str:
        """Generate a temp directory path."""
        random_hex = utils.generate_fixed_length_token(length=32)
        random_suffix = utils.generate_fixed_length_token(length=6).upper()
        return f"/tmp/systemd-private-{random_hex}-upower.service-{random_suffix}"

    # Properties
    @property
    def target(self) -> target.Target:
        return self.__target

    @property
    def action_manager(self) -> action.ActionsManager:
        return self.__action_manager

    @property
    def working_directory(self) -> str:
        return self._working_directory
