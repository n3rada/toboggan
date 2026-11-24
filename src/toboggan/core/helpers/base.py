# toboggan/core/helpers/base.py

# Built-in imports
from abc import ABC, abstractmethod


class OSHelperBase(ABC):
    """Abstract base class for OS-specific operations."""

    def __init__(
        self,
        executor,
    ):
        self._executor = executor
        self._stdin_path = None
        self._stdout_path = None

    @abstractmethod
    def start_named_pipe(self, action_class, **kwargs) -> None:
        """Start a named pipe action for interactive sessions."""
        raise NotImplementedError()

    @abstractmethod
    def get_current_path(self) -> str:
        """Return the current working directory on the remote system."""
        raise NotImplementedError()

    @abstractmethod
    def format_working_directory(self) -> str:
        """Generate a temporary working directory path for the remote system."""
        raise NotImplementedError()

    @abstractmethod
    def get_hostname(self) -> str:
        """Return the hostname of the remote system."""
        raise NotImplementedError()

    @abstractmethod
    def get_current_user(self) -> str:
        """Return the current user on the remote system."""
        raise NotImplementedError()

    @property
    def stdin_path(self) -> str:
        """Return the path used for stdin redirection."""
        return self._stdin_path

    @stdin_path.setter
    def stdin_path(self, path: str) -> None:
        self._stdin_path = path

    @property
    def stdout_path(self) -> str:
        """Return the path used for stdout redirection."""
        return self._stdout_path

    @stdout_path.setter
    def stdout_path(self, path: str) -> None:
        self._stdout_path = path
