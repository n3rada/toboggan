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

        # If server is slow, override with actual RTT
        avg_rtt = self._executor.avg_response_time
        if avg_rtt and avg_rtt > self._read_interval:
            self._read_interval = (
                avg_rtt  # Don't poll faster than the target can respond
            )

            self._logger.info(f"⏱️ Adjusted reading interval based on average RTT.")

        self._logger.info(f"🔁 Reading interval: {self._read_interval:.2f} seconds")

        req_per_sec = 1 / self._read_interval
        req_per_min = req_per_sec * 60

        self._logger.info(
            f"📡 Approx. requests: {req_per_sec:.2f}/sec | {req_per_min:.0f}/min"
        )

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

    def __init__(self, target_os: str = "linux"):

        if target_os not in ["linux", "windows"]:
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

                try:
                    wrapper = ModuleWrapper(file_path)
                    cls = wrapper.get_class(must_inherit=BaseAction)
                    if not cls:
                        continue

                    parameters = self.__extract_parameters(wrapper)
                    description = getattr(cls, "DESCRIPTION", None)

                    actions[action_name] = {
                        "path": file_path,
                        "parameters": parameters,
                    }

                    if description:
                        actions[action_name]["description"] = description

                except Exception as exc:
                    self._logger.warning(f"⚠️ Skipping action '{action_name}': {exc}")

        return actions

    def __extract_parameters(self, wrapper: ModuleWrapper) -> list:

        try:
            # Get the class that inherits from BaseAction
            action_cls = wrapper.get_class(must_inherit=BaseAction)
            if not action_cls:
                self._logger.warning(f"⚠️ No action class found in {wrapper.name}")
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
            self._logger.warning(
                f"⚠ Failed to extract parameters from {wrapper.name}: {exc}"
            )
            return []

    def get_action(self, name: str) -> BaseAction:
        """
        Retrieves an action, prioritizing user actions over system ones.

        Args:
            name (str): The action category (e.g., "download", "interactivity").

        Returns:
            BaseAction instance if found, else None.
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
                    self._logger.info(
                        f"📦 Loaded user action '{name}' (last modified: {formatted_time})"
                    )
                    return action
            except Exception as e:
                self._logger.warning(f"⚠️ Failed to load user action '{name}': {e}")

        # Fallback to system action
        if system_module_path.exists():
            if action := self.load_action_from_path(system_module_path):
                self._logger.info(f"📦 Loaded system action '{name}'")
                return action

        # No valid action found
        self._logger.error(f"❌ No valid action found for '{name}'")
        return None

    def load_action_from_path(self, file_path: Path) -> BaseAction:
        """
        Dynamically loads an action class from a Python file using ModuleWrapper.

        Args:
            file_path (Path): The full path to the action file.

        Returns:
            BaseAction class if found, else None.
        """
        try:
            wrapper = ModuleWrapper(file_path)
            action_class = wrapper.get_class(must_inherit=BaseAction)
            if action_class:
                self._logger.debug(f"👀 Loaded action class: {action_class.__name__}")
                return action_class
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
