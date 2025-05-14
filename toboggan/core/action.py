# Standard library imports
from abc import ABC, abstractmethod
import os
import inspect
from datetime import datetime
from pathlib import Path


# Third party library imports
from modwrap import ModuleWrapper


# Local application/library specific imports
from toboggan.core import logbook


class BaseAction(ABC):
    """Base class for all modules in Toboggan"""

    def __init__(self, executor):
        self._logger = logbook.get_logger()
        self._executor = executor

    @abstractmethod
    def run(self, *args, **kwargs):
        """Every action must implement this method"""
        pass


class NamedPipe(BaseAction):
    """Abstract base class for Named Pipe actions"""

    def __init__(
        self,
        executor,
        read_interval: float = 0.4,
        command_in: str = None,
        command_out: str = None,
    ):
        super().__init__(executor)

        if command_out is None:
            self._stdout = self._executor.os_helper.stealthy_name()
        else:
            self._stdout = command_out

        if command_in is None:
            self._stdin = self._executor.os_helper.stealthy_name()
        else:
            self._stdin = command_in

        self._logger.info(f"Using stdin: {self._stdin}")
        self._logger.info(f"Using stdout: {self._stdout}")

        self._read_interval = read_interval
        self._logger.info(f"Reading interval: {read_interval} seconds")
        req_per_minute = 60 / read_interval

        self._logger.info(f"Requests per minute: {req_per_minute}")

    @abstractmethod
    def setup(self, read_interval: float = 0.4, session_identifier: str = None):
        """Every NamedPipe action must implement this method"""
        pass

    @abstractmethod
    def execute(self, command: str):
        """Every NamedPipe action must implement this method"""
        pass

    def stop(self):
        self._logger.info("Stopping named pipe")
        self._stop()

        self._logger.info("Killing running session")
        self._executor.remote_execute(f"/usr/bin/pkill -TERM -f {self._stdin}")

    @abstractmethod
    def _stop(self):
        """Every NamedPipe action must implement this method"""
        pass


class ActionsManager:
    """Dynamically loads and manages Toboggan actions from system and user directories."""

    def __init__(self, target_os: str = "unix"):

        if target_os not in ["unix", "windows"]:
            raise ValueError(
                f"Invalid target OS '{target_os}'. Must be 'unix' or 'windows'."
            )

        self.__os = target_os

        self._logger = logbook.get_logger()

        self.__system_actions_path = Path(__file__).parent.parent / "actions"
        self._logger.debug(f"System actions path: {self.__system_actions_path}")

        self.__user_actions_path = self.__get_user_module_dir()
        self._logger.debug(f"User actions path: {self.__user_actions_path}")

    def get_actions(self) -> dict:

        ignored_actions = {"hide", "unhide"}

        actions = {}

        if self.__system_actions_path.exists():
            for action_file in self.__system_actions_path.iterdir():
                action_name = action_file.stem

                if action_name in ignored_actions:
                    continue

                file_path = action_file / f"{self.__os}.py"
                description = self.__extract_description(file_path)

                actions[action_name] = {
                    "path": file_path,
                    "parameters": self.__extract_parameters(file_path),
                }

                if description is not None:
                    actions[action_name]["description"] = description

        if self.__user_actions_path.exists():
            for action_file in self.__user_actions_path.iterdir():
                action_name = action_file.stem

                if action_name in ignored_actions:
                    continue

                file_path = action_file / f"{self.__os}.py"
                description = self.__extract_description(file_path)

                actions[action_name] = {
                    "path": file_path,
                    "parameters": self.__extract_parameters(file_path),
                }

                if description is not None:
                    actions[action_name]["description"] = description

        return actions

    def get_action(self, name: str) -> BaseAction:
        """
        Retrieves an action, prioritizing user actions over system ones.

        Args:
            name (str): The action category (e.g., "download", "interactivity").

        Returns:
            BaseAction instance if found, else None.
        """
        self._logger.info(f"Loading action named '{name}'")

        name = f"{name}/{self.__os}"
        system_module_path = self.__system_actions_path / f"{name}.py"
        user_module_path = self.__user_actions_path / f"{name}.py"

        # Step 1: Try loading the system action
        if action := self.load_action_from_path(system_module_path):
            self._logger.info(f"✅ Loaded system action")
            return action

        # Step 2: Check if a user-defined action exists
        if user_module_path.exists():
            last_modified = user_module_path.stat().st_mtime
            formatted_time = datetime.fromtimestamp(last_modified).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self._logger.info(f"📝 Found user action (Last modified: {formatted_time})")

            if action := self.load_action_from_path(user_module_path):
                return action

        # Step 3: If no action was loaded, log an error
        self._logger.error(f"❌ No valid action found for '{name}'.")
        return None

    def load_action_from_path(self, file_path: Path) -> BaseAction:
        """
        Dynamically loads an action class from a Python file using modwrap.

        Args:
            file_path (Path): The full path to the action file.

        Returns:
            BaseAction class if found, else None.
        """
        try:
            wrapper = ModuleWrapper(file_path)
            for name in dir(wrapper.module):
                obj = getattr(wrapper.module, name)
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BaseAction)
                    and obj is not BaseAction
                ):
                    return obj
        except Exception as exc:
            self._logger.error(f"❌ Failed to load module: {file_path.name} ({exc})")
        return None

    def __get_user_module_dir(self) -> Path:
        """Get the user action directory (XDG for Linux/macOS, LOCALAPPDATA for Windows)."""
        if os.name == "nt":
            local_appdata = os.getenv(
                "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
            )
            return Path(local_appdata) / "toboggan" / "actions"

        xdg_data_home = os.getenv(
            "XDG_DATA_HOME", str(Path.home() / ".local" / "share")
        )
        return Path(xdg_data_home) / "toboggan" / "actions"

    def __extract_description(self, file_path: Path) -> str | None:
        wrapper = ModuleWrapper(file_path)
        cls = wrapper.get_class(must_inherit=BaseAction)

        if cls and hasattr(cls, "DESCRIPTION"):
            return cls.DESCRIPTION

        return None

    def __extract_parameters(self, file_path: Path) -> list:
        """
        Extracts parameters of the action's entry point using modwrap.
        Prioritizes __init__ for NamedPipe-based actions, else uses run().
        """
        try:
            wrapper = ModuleWrapper(file_path)

            # NamedPipe-based actions → use __init__ signature
            for name in dir(wrapper.module):
                obj = getattr(wrapper.module, name)
                if inspect.isclass(obj) and issubclass(obj, NamedPipe):
                    sig = wrapper.get_signature(f"{name}.__init__")
                    break
            else:
                # Standard actions → use run() method of the first BaseAction
                for name in dir(wrapper.module):
                    obj = getattr(wrapper.module, name)
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, BaseAction)
                        and obj is not BaseAction
                    ):
                        sig = wrapper.get_signature(f"{name}.run")
                        break
                else:
                    return []

            return [
                (
                    f"{param} ({value['default']})"
                    if value["default"] is not None
                    else param
                )
                for param, value in sig.items()
            ]

        except Exception as e:
            self._logger.warning(
                f"⚠ Failed to extract parameters from {file_path.name}: {e}"
            )
            return []
