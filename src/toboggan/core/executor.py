# toboggan/core/executor.py

# Built-in imports
import random
import time
import base64

# External library imports
from loguru import logger

# Local application/library specific imports
from . import action
from . import target
from .utils.common import SingletonMeta
from .helpers.linux import LinuxHelper
from .helpers.windows import WindowsHelper
from .helpers.base import OSHelperBase


class Executor(metaclass=SingletonMeta):

    def __init__(
        self,
        execute_method: callable = None,
        shell: str = None,
        working_directory: str = None,
        target_os: str = None,
        base64_wrapping: bool = False,
        obfuscation: bool = False,
        custom_paths: list = None,
    ):
        if execute_method is None:
            raise ValueError("Executor should have an execute callable method.")

        self.__execute = execute_method
        self.__base64_wrapping = base64_wrapping
        self.__obfuscation = False

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

        if obfuscation:
            # Temporarily disable obfuscation during action initialization
            self.__obfuscation = False

            # For Windows with obfuscation, force PowerShell mode
            if self.__os == "windows" and hasattr(self._os_helper, "force_powershell"):
                self._os_helper.force_powershell()

            self.__obfuscation_action = self.__action_manager.get_action("hide")(
                executor=self
            )

            self.__unobfuscation_action = self.__action_manager.get_action("unhide")(
                executor=self
            )

            self.__obfuscation = True
            logger.success("✅ Obfuscation enabled")
        else:
            self.__obfuscation = False

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

            self.remote_execute(command=f'mkdir "{self._working_directory}"')
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
            logger.trace(f"🔍 Validating shell: {self._shell}")
            if not self.__validate_shell():
                if isinstance(self._os_helper, LinuxHelper):
                    if linux_shells:
                        next_shell = linux_shells.pop(0)
                        logger.info(f"🔄 Falling back to {next_shell}")
                        self.shell = next_shell
                        continue

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

        # Only align to 1024 for larger sizes
        if size >= 1024 and size % 1024 != 0:
            logger.warning(
                f"Chunk size {size} is not a multiple of 1024. Rounding down to nearest 1024."
            )
            size = (size // 1024) * 1024
        elif size >= 1024:
            # Already aligned
            pass
        else:
            # Small size - no alignment needed
            logger.debug(f"Using small chunk size: {size} bytes (no alignment)")

        if size <= 0:
            logger.error("❌ Chunk size must be positive after alignment.")
            return

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
        logger.debug(f"📏 Chunk max size set to: {self._chunk_max_size} bytes")

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
        bypass_obfuscation: bool = False,
    ) -> str:
        """
        Executes the specified command within the module.

        Args:
            command (str): Command to be executed remotely.
            timeout (float, optional): Timeout for command execution.
            retry (bool, optional): Whether to retry on failure.
            debug (bool, optional): Enable or disable debug logging for this execution.
            bypass_obfuscation (bool, optional): Bypass obfuscation check.

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
        if not bypass_obfuscation and self.__obfuscation:
            command = self.__obfuscation_action.run(command)

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
                    logger.warning(f"⏳ Retrying after {sleep_time:.2f} seconds..")
                time.sleep(sleep_time)

        if not result:
            return ""

        logger.trace(f"📩 Received raw output: {result!r}")

        # Attempt to de-obfuscate the result if obfuscation was used
        if not bypass_obfuscation and self.__obfuscation:
            try:
                result = self.__unobfuscation_action.run(result)
                logger.trace(f"🔓 De-obfuscated output: {result!r}")
            except ValueError:
                if debug:
                    logger.error(
                        f"⚠️ Failed to de-obfuscate command output.\n"
                        f"\t• Original Command: {command!r}\n"
                        f"\t• Received Output: {result!r}"
                    )
                raise

        return str(result)

    def delete_working_directory(self) -> None:
        """
        Deletes the remote working directory if it has been created.
        Uses rm -rf to force removal of all contents.
        """
        if not self.has_working_directory:
            logger.debug("No working directory to delete.")
            return

        try:
            logger.debug(
                f"🗑️ Deleting remote working directory: {self._working_directory}"
            )
            # Use -rf to force deletion, bypass obfuscation for cleanup reliability
            self.remote_execute(
                f"rm -rf {self._working_directory}",
                debug=False,
                bypass_obfuscation=True,
            )

        except Exception as exc:
            logger.warning(f"⚠️ Failed to delete remote working directory: {exc}")

    def calculate_max_chunk_size(self, min_size=10, max_size=262144) -> int:
        """
        Determines the maximum command chunk size accepted by the remote shell.
        First tries the maximum size directly, then falls back to binary search if needed.
        Sizes >= 1024 are aligned to 1024, smaller sizes use natural alignment.
        Validates output integrity by checking the last characters aren't truncated.
        Uses marker truncation and output length to deduce the actual working size.

        Returns:
            int: Maximum command size in bytes that the remote shell accepts.
        """

        def align_size(size: int) -> int:
            """Align size appropriately - 1024 for large sizes, no alignment for small."""
            if size >= 1024:
                return (size // 1024) * 1024
            return size

        # Align initial bounds
        max_size = align_size(max_size)

        def test_command_size(size: int) -> tuple[bool, int]:
            """
            Test if a command of given size works without truncation.

            Returns:
                tuple[bool, int]: (success, actual_size)
                - success: True if output is complete, False if truncated
                - actual_size: The deduced actual size based on marker or output length
            """
            # Use a distinctive marker at the end to verify output isn't truncated
            marker = "ENDMARKER"
            marker_len = len(marker)

            # Calculate junk size: total - "echo " - marker
            junk_size = size - len("echo ") - marker_len

            if junk_size < 0:
                return False, 0

            junk = "A" * junk_size
            cmd = f"echo {junk}{marker}"

            try:
                result = self.remote_execute(
                    cmd,
                    timeout=5,
                    retry=False,
                    raise_on_failure=True,
                    debug=False,
                )

                # Check if the output ends with our marker (strip whitespace)
                output_stripped = result.strip()

                if output_stripped.endswith(marker):
                    # Full marker present - no truncation
                    return True, size

                # Check for partial marker to deduce actual size
                for i in range(len(marker) - 1, 0, -1):
                    partial_marker = marker[:i]
                    if output_stripped.endswith(partial_marker):
                        # Found partial marker - calculate actual size
                        chars_missing = len(marker) - i
                        actual_size = size - chars_missing
                        logger.debug(
                            f"📊 Partial marker detected: '{partial_marker}' "
                            f"({i}/{len(marker)} chars) - deduced size: {actual_size} bytes"
                        )
                        return False, actual_size

                # No marker found - use output length to estimate upper bound for binary search
                # This is unreliable as final answer but useful to narrow search space
                output_len = len(output_stripped)
                if output_len > 0:
                    # Account for "echo " command overhead (5 chars)
                    estimated_size = output_len + len("echo ")
                    logger.debug(
                        f"📊 No marker found - output length: {output_len} chars, "
                        f"estimated upper bound: {estimated_size} bytes (for search optimization)"
                    )
                    return False, estimated_size

                logger.debug(f"❌ No output at {size} bytes")
                return False, 0

            except Exception as e:
                logger.debug(f"❌ Exception at {size} bytes: {e}")
                return False, 0

        # Try maximum size first
        logger.info(f"📏 Trying maximum size: {max_size} bytes")

        success, actual_size = test_command_size(max_size)
        if success:
            logger.success(f"✅ Maximum size {max_size} bytes works!")
            return max_size

        # Adjust binary search range based on initial test
        low = min_size
        high = max_size
        best = 0

        if actual_size > 0:
            # Got output or partial marker - use to optimize search range
            estimated_upper = actual_size * 4  # Give 4x headroom
            estimated_upper_aligned = align_size(estimated_upper)

            if estimated_upper_aligned < max_size:
                # Narrow the search space - likely limit is around estimated size
                high = min(estimated_upper_aligned, max_size)
                logger.info(
                    f"📊 Output suggests limit around {actual_size} bytes - "
                    f"narrowing search to {min_size}-{high} bytes"
                )
            else:
                logger.info("❌ Maximum size failed, using full binary search range")
        else:
            logger.info("❌ No output from maximum size test")

        # Binary search for the actual limit
        logger.info(f"🔢 Binary search range: {min_size} to {high} bytes")

        while low <= high:
            # Align mid appropriately
            mid = (low + high) // 2
            mid = align_size(mid)

            # Avoid getting stuck
            if mid == best or mid < low:
                break

            logger.info(f"📏 Trying size: {mid} bytes")

            success, actual_size = test_command_size(mid)
            if success:
                logger.info(f"✅ Success at {mid} bytes (output verified)")
                best = mid
                low = mid + (1024 if mid >= 1024 else 64)
            elif actual_size > 0 and actual_size < mid:
                # We found truncation and can deduce the actual size
                actual_size_aligned = align_size(actual_size)
                logger.info(
                    f"📊 Truncation at {mid} bytes - deduced: {actual_size_aligned} bytes"
                )
                if actual_size_aligned > best and actual_size_aligned >= min_size:
                    # Verify this deduced size
                    verify_success, _ = test_command_size(actual_size_aligned)
                    if verify_success:
                        best = actual_size_aligned
                        logger.success(f"✅ Verified deduced size: {best} bytes")
                        # Deduced size verified - this is our answer
                        return best
                    else:
                        logger.debug(
                            f"❌ Deduced size {actual_size_aligned} verification failed"
                        )

                # Verification failed or skipped - search below the truncation point
                high = actual_size_aligned - (
                    1024 if actual_size_aligned >= 1024 else 64
                )
            else:
                logger.info(f"❌ Failed at {mid} bytes")
                high = mid - (1024 if mid >= 1024 else 64)

            logger.debug(f"🔁 Search range: low={low}, high={high}, best={best}")

        if best > 0:
            logger.success(f"📏 Final maximum command size: {best} bytes")
        else:
            logger.error(f"❌ Could not determine a working command size")

        return best

    # Private methods

    def __guess_os(self) -> str:
        logger.debug("🔍 Guessing remote OS")

        ls_output = self.remote_execute(command="ls /", retry=False).strip().lower()

        if ls_output:
            if "bin" in ls_output or "etc" in ls_output:
                logger.info("🖥️ Detected Linux OS via ls /.")
                return "linux"
            if "windows" in ls_output or "program files" in ls_output:
                logger.info("🖥️ Detected Windows OS via ls /.")
                return "windows"

        ver_output = self.remote_execute(command="ver", retry=False).strip().lower()

        if ver_output and "microsoft" in ver_output:
            logger.info("🖥️ Detected Windows OS via ver.")
            return "windows"

        logger.info("🖥️ Assuming Linux OS.")
        return "linux"

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
                        bypass_obfuscation=True,
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
