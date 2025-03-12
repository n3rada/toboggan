# Standard library imports
from abc import ABC, abstractmethod
import importlib
import os
import sys
import re
import inspect
from datetime import datetime
from pathlib import Path

# Local application/library specific imports
from toboggan.core import logbook
from toboggan.core import utils


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
            command_out = utils.generate_fixed_length_token(length=8)

        if command_in is None:
            command_in = utils.generate_fixed_length_token(length=8)

        self._logger.info(f"Using stdin: {command_in}")
        self._logger.info(f"Using stdout: {command_out}")

        self._stdin = f"{self._executor.working_directory}/{command_in}"
        self._stdout = f"{self._executor.working_directory}/{command_out}"

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

        self.__logger = logbook.get_logger()

        self.__system_actions_path = Path(__file__).parent.parent / "actions"
        self.__logger.debug(f"System actions path: {self.__system_actions_path}")

        self.__user_actions_path = self.__get_user_module_dir()
        self.__logger.debug(f"User actions path: {self.__user_actions_path}")

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
        self.__logger.info(f"Loading action named '{name}'")

        name = f"{name}/{self.__os}"
        system_module_path = self.__system_actions_path / f"{name}.py"
        user_module_path = self.__user_actions_path / f"{name}.py"

        # Step 1: Try loading the system action
        if action := self.load_action_from_path(system_module_path):
            self.__logger.info(f"✅ Loaded system action")
            return action

        # Step 2: Check if a user-defined action exists
        if user_module_path.exists():
            last_modified = user_module_path.stat().st_mtime
            formatted_time = datetime.fromtimestamp(last_modified).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self.__logger.info(
                f"📝 Found user action (Last modified: {formatted_time})"
            )

            if action := self.load_action_from_path(user_module_path):
                return action

        # Step 3: If no action was loaded, log an error
        self.__logger.error(f"❌ No valid action found for '{name}'.")
        return None

    def load_action_from_path(self, file_path: Path) -> BaseAction:
        """
        Dynamically loads an action from a Python file.

        Args:
            file_path (Path): The full path to the action file.

        Returns:
            BaseAction class if successful, None otherwise.
        """
        if not file_path.exists() or not file_path.suffix == ".py":
            return None

        module_name = (
            f"toboggan_action_{file_path.stem}"  # Unique module name for dynamic import
        )
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))

        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Find a class that inherits from BaseAction
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, BaseAction) and cls is not BaseAction:
                    return cls

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

    def __extract_description(self, file_path: Path) -> str:
        """Extracts the DESCRIPTION from an action file."""

        match = re.search(
            pattern=r'DESCRIPTION\s*=\s*["\'](.+?)["\']',
            string=file_path.read_text(),
            flags=re.MULTILINE,
        )

        if match:
            return match.group(1)

        return None

    def __extract_parameters(self, file_path: Path) -> list:
        """
        Extracts function parameters from either the `run` method (for standard actions)
        or the `__init__` method (for NamedPipe-based actions).
        """
        self.__logger.debug(f"Extracting parameters from: {file_path}")
        file_content = file_path.read_text()

        if re.search(r"class\s+\w+\(.*?NamedPipe.*?\):", file_content):
            self.__logger.debug("NamedPipe class detected.")
            match = re.search(
                pattern=r"def __init__\s*\(\s*self\s*,?(.*?)\):",
                string=file_content,
                flags=re.MULTILINE | re.DOTALL,
            )
        else:
            self.__logger.debug("Common action detected.")
            match = re.search(
                pattern=r"def run\((.*?)\):",
                string=file_content,
                flags=re.MULTILINE | re.DOTALL,
            )

        if match:
            # Extract parameter list (excluding `self`)
            params = match.group(1).split(",")[1:]

            self.__logger.debug(f"Params: {params}")

            # Format parameters with default values
            formatted_params = []
            for param in params:
                parts = param.split("=")
                param_name = parts[0].split(":")[0].strip()
                default_value = f" ({parts[1].strip()})" if len(parts) > 1 else ""
                formatted_params.append(f"{param_name}{default_value}")

            return formatted_params

        return None
