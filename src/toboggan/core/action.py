# toboggan/core/action.py

# Standard library imports
from abc import ABC, abstractmethod
import os
from datetime import datetime
from pathlib import Path

# Third party library imports
from loguru import logger
from modwrap import ModuleWrapper


class BaseAction(ABC):
    """Abstract base class for all actions in Toboggan.

    Provides the foundation for implementing custom actions that can be executed
    on remote systems. All actions must inherit from this class and implement
    the run() method.

    Attributes:
        _executor: The executor instance for remote command execution.
        _os_helper: OS-specific helper instance for platform operations.
    """

    def __init__(self, executor):
        """Initialize the action with an executor instance.

        Args:
            executor: The Executor instance that provides remote execution
                capabilities and OS helper access.
        """
        self._executor = executor
        self._os_helper = executor.os_helper

    @abstractmethod
    def run(self, *args, **kwargs):
        """Execute the action's main functionality.

        This method must be implemented by all subclasses to define the specific
        behavior of the action.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            The result of the action execution. Return type varies by implementation.
        """
        pass


class NamedPipe(BaseAction):
    """Abstract base class for Named Pipe-based inter-process communication.

    Provides a framework for implementing semi-interactive shells using named pipes
    (FIFO) for bidirectional communication with remote systems. Subclasses implement
    OS-specific pipe creation and management.

    Attributes:
        _stdin: Path to the stdin pipe for command input.
        _stdout: Path to the stdout pipe for command output.
        _read_interval: Time interval between pipe read operations.
    """

    def __init__(
        self,
        executor,
        read_interval: float = 0.3,
        stdin_path: str = None,
        stdout_path: str = None,
    ):
        """Initialize a NamedPipe action for inter-process communication.

        Sets up named pipes for bidirectional communication with the remote system.
        If pipe paths are not specified, generates stealthy random filenames to avoid
        detection. Calculates and logs estimated polling frequency based on network
        round-trip time.

        Args:
            executor: The Executor instance responsible for remote command execution
                and OS helper access.
            read_interval: Time interval in seconds between read operations on the pipe.
                Defaults to 0.3. The actual poll cycle will be longer due to network RTT.
            stdin_path: Full path to the input (stdin) pipe. If None, a stealthy name
                is automatically generated. Defaults to None.
            stdout_path: Full path to the output (stdout) pipe. If None, a stealthy name
                is automatically generated. Defaults to None.

        Note:
            The effective polling frequency is read_interval + average RTT, which affects
            the number of requests per second/minute to the remote system.
        """
        super().__init__(executor)

        if stdout_path is None:
            self._stdout = self._executor.os_helper.random_system_file_name()
        else:
            self._stdout = stdout_path

        if stdin_path is None:
            self._stdin = self._executor.os_helper.random_system_file_name()
        else:
            self._stdin = stdin_path

        logger.info(f"Using stdin file: {self._stdin}")
        logger.info(f"Using stdout file: {self._stdout}")

        self._read_interval = float(read_interval)

        logger.info(f"🔁 Reading interval: {self._read_interval:.2f} seconds")

        # Note: The actual polling frequency will be read_interval + avg request execution time
        avg_rtt = self._executor.avg_response_time
        if avg_rtt:
            estimated_poll_freq = self._read_interval + avg_rtt
            logger.info(
                f"⏱️ Estimated total poll cycle: ~{estimated_poll_freq:.2f}s (interval + avg RTT)"
            )

        req_per_sec = 1 / (self._read_interval + (avg_rtt or 0))
        req_per_min = req_per_sec * 60

        logger.info(
            f"📡 Approx. requests: {req_per_sec:.2f}/sec | {req_per_min:.0f}/min"
        )

    # Abstract methods
    @abstractmethod
    def setup(self, read_interval: float = 0.4, session_identifier: str = None):
        """Set up the named pipes on the remote system.

        Creates the necessary pipes and initializes the communication channel.
        Implementation details vary by operating system.

        Args:
            read_interval: Time interval in seconds between read operations. Defaults to 0.4.
            session_identifier: Optional identifier for the session. Defaults to None.

        Raises:
            RuntimeError: If pipe creation or initialization fails.
        """
        pass

    @abstractmethod
    def execute(self, command: str):
        """Execute a command through the named pipe.

        Writes the command to the stdin pipe for execution on the remote system.
        Output will be available through the stdout pipe.

        Args:
            command: The command string to execute on the remote system.

        Raises:
            RuntimeError: If command execution or pipe communication fails.
        """
        pass

    @abstractmethod
    def _stop(self):
        """Clean up named pipe resources on the remote system.

        Stops background processes, closes pipes, and removes temporary files.
        This method is called internally by stop() and must be implemented by
        all subclasses.

        Note:
            This is an internal method. Use stop() for public cleanup operations.
        """
        pass

    # Public methods
    def stop(self):
        """Stop the named pipe action and clean up resources.

        Logs the stop operation and delegates to the subclass-specific _stop()
        implementation for cleanup of pipes and background processes.
        """
        logger.info("Stopping named pipe")
        self._stop()


class ActionsManager:
    """Dynamically loads and manages Toboggan actions from system and user directories.

    Provides discovery, loading, and instantiation of action modules. Supports both
    system-provided actions and user-defined custom actions, with user actions taking
    priority when name conflicts occur.

    Attributes:
        __os: Target operating system ('linux' or 'windows').
        __system_actions_path: Path to built-in system actions.
        __user_actions_path: Path to user-defined custom actions.
    """

    # Constructor
    def __init__(self, target_os: str = "linux"):
        """Initialize the actions manager for a specific operating system.

        Sets up paths to system and user action directories based on the target OS.

        Args:
            target_os: Target operating system. Must be 'linux' or 'windows'.
                Defaults to 'linux'.

        Raises:
            ValueError: If target_os is not 'linux' or 'windows'.
        """

        if target_os not in ["linux", "windows"]:
            raise ValueError(
                f"Invalid target OS '{target_os}'. Must be 'unix' or 'windows'."
            )

        self.__os = target_os

        self.__system_actions_path = Path(__file__).parent / "actions"
        logger.debug(f"System actions path: {self.__system_actions_path}")

        self.__user_actions_path = self.__get_user_module_dir()
        logger.debug(f"User actions path: {self.__user_actions_path}")

    # Dunders

    # Properties

    # Public methods
    def get_actions(self) -> dict:
        """Discover and catalog all available actions for the target OS.

        Scans both system and user action directories, loading metadata for each
        compatible action. Ignores internal actions like 'hide' and 'unhide'.

        Returns:
            Dictionary mapping action names to their metadata, including:
                - path: Full path to the action file
                - parameters: List of parameters the action accepts
                - description: Human-readable description (if available)

        Note:
            User actions can override system actions with the same name.
            Actions without valid BaseAction classes are skipped with a warning.
        """
        ignored_actions = {"hide", "unhide"}
        actions = {}

        for source_path in [self.__system_actions_path, self.__user_actions_path]:
            if not source_path.exists():
                continue

            for action_dir in source_path.iterdir():
                action_name = action_dir.stem
                if action_name in ignored_actions:
                    continue

                file_path = action_dir / f"{self.__os}.py"

                if not file_path.exists():
                    continue

                logger.trace(f"Found action: {action_name} at {file_path}")

                try:
                    wrapper = ModuleWrapper(file_path)

                    logger.trace(f"Wrapped action: {repr(wrapper)}")

                    cls = wrapper.get_class(must_inherit=BaseAction)

                    if not cls:
                        continue

                    logger.trace(f"Found action class: {cls.__name__}")

                    parameters = self.__extract_parameters(wrapper)
                    description = getattr(cls, "DESCRIPTION", None)

                    actions[action_name] = {
                        "path": file_path,
                        "parameters": parameters,
                    }

                    if description:
                        actions[action_name]["description"] = description

                except Exception:
                    logger.exception(f"⚠️ Skipping action '{action_name}'")

        return actions

    def get_action(self, name: str) -> BaseAction:
        """Retrieve and load an action class by name.

        Searches for the action in both user and system directories, prioritizing
        user-defined actions when both exist. Logs the source and last modified
        timestamp for user actions.

        Args:
            name: The action name (e.g., "download", "fifo", "upload").
                OS-specific variants are automatically resolved.

        Returns:
            The action class (subclass of BaseAction) if found, None otherwise.

        Note:
            User actions in ~/.local/share/toboggan/actions (Linux) or
            %LOCALAPPDATA%\toboggan\actions (Windows) take precedence over
            built-in system actions.
        """
        name_with_os = f"{name}/{self.__os}"
        system_module_path = self.__system_actions_path / f"{name_with_os}.py"
        user_module_path = self.__user_actions_path / f"{name_with_os}.py"

        # Prioritize user-defined actions
        if user_module_path.exists():
            try:
                last_modified = user_module_path.stat().st_mtime
                formatted_time = datetime.fromtimestamp(last_modified).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if action := self.load_action_from_path(user_module_path):
                    logger.info(
                        f"📦 Loaded user action '{name}' (last modified: {formatted_time})"
                    )
                    return action
            except Exception as e:
                logger.warning(f"⚠️ Failed to load user action '{name}': {e}")

        # Fallback to system action
        if system_module_path.exists():
            if action := self.load_action_from_path(system_module_path):
                logger.info(f"📦 Loaded system action '{name}'")
                return action

        # No valid action found
        logger.error(f"❌ No valid action found for '{name}'")
        return None

    def load_action_from_path(self, file_path: Path) -> BaseAction:
        """Dynamically load an action class from a Python file.

        Uses ModuleWrapper to safely import and inspect the Python file, extracting
        the first class that inherits from BaseAction.

        Args:
            file_path: Full path to the action's Python file.

        Returns:
            The action class (subclass of BaseAction) if found and valid,
            None if no valid action class exists or loading fails.

        Note:
            Errors during module loading are logged but do not raise exceptions.
        """
        try:
            wrapper = ModuleWrapper(file_path)
            action_class = wrapper.get_class(must_inherit=BaseAction)
            if action_class:
                logger.debug(f"Loaded action class: {action_class.__name__}")
                return action_class
        except Exception as exc:
            logger.error(f"Failed to load module: {file_path.name} ({exc})")

        return None

    # Private methods
    def __extract_parameters(self, wrapper: ModuleWrapper) -> list:
        """Extract parameter information from an action class.

        Inspects the action's __init__ (for NamedPipe) or run() method to extract
        parameter names and default values for documentation and CLI generation.

        Args:
            wrapper: ModuleWrapper instance containing the loaded action module.

        Returns:
            List of parameter strings formatted as 'name (default)' or 'name' if no default.
            Returns empty list if extraction fails.
        """
        try:
            # Get the class that inherits from BaseAction
            action_cls = wrapper.get_class(must_inherit=BaseAction)
            if not action_cls:
                logger.warning(f"⚠️ No action class found in {wrapper.name}")
                return []

            class_name = action_cls.__name__
            method_name = "__init__" if issubclass(action_cls, NamedPipe) else "run"
            signature = wrapper.get_signature(f"{class_name}.{method_name}")

            return [
                (
                    f"{param} ({value['default']})"
                    if value["default"] is not None
                    else param
                )
                for param, value in signature.items()
            ]

        except Exception as exc:
            logger.warning(f"⚠ Failed to extract parameters from {wrapper.name}: {exc}")
            return []

    def __get_user_module_dir(self) -> Path:
        """Get the platform-specific user action directory.

        Returns the appropriate directory for user-defined actions based on OS
        conventions: XDG Base Directory specification for Linux/macOS, and
        LocalAppData for Windows.

        Returns:
            Path to user actions directory:
                - Linux/macOS: $XDG_DATA_HOME/toboggan/actions or ~/.local/share/toboggan/actions
                - Windows: %LOCALAPPDATA%\toboggan\actions or ~/AppData/Local/toboggan/actions
        """
        if os.name == "nt":
            local_appdata = os.getenv(
                "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
            )
            return Path(local_appdata) / "toboggan" / "actions"

        xdg_data_home = os.getenv(
            "XDG_DATA_HOME", str(Path.home() / ".local" / "share")
        )
        return Path(xdg_data_home) / "toboggan" / "actions"
