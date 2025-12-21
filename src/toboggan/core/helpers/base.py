# toboggan/core/helpers/base.py

# Built-in imports
from abc import ABC, abstractmethod


class OSHelperBase(ABC):
    """
    Abstract base class for OS-specific operations.
    """

    def __init__(
        self,
        executor,
    ):
        self._executor = executor
        self._stdin_path = None
        self._stdout_path = None

    @abstractmethod
    def start_named_pipe(self, action_class, **kwargs) -> None:
        raise NotImplementedError()

    @abstractmethod
    def get_current_path(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def format_working_directory(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def get_hostname(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def get_current_user(self) -> str:
        raise NotImplementedError()

    @property
    def stdin_path(self) -> str:
        return self._stdin_path

    @stdin_path.setter
    def stdin_path(self, path: str) -> None:
        self._stdin_path = path

    @property
    def stdout_path(self) -> str:
        return self._stdout_path

    @stdout_path.setter
    def stdout_path(self, path: str) -> None:
        self._stdout_path = path
