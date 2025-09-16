from abc import ABC, abstractmethod

# Local imports
from toboggan.core import logbook


class OSHelperBase(ABC):
    """
    Abstract base class for OS-specific operations.
    """

    def __init__(
        self,
        executor,
    ):
        self._executor = executor
        self._logger = logbook.get_logger()

    @abstractmethod
    def start_named_pipe(self, action_class, **kwargs) -> None:
        raise NotImplementedError()

    @abstractmethod
    def get_current_path(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def format_working_directory(self) -> str:
        raise NotImplementedError()

    @property
    def shell(self) -> str:
        return self._executor.shell
