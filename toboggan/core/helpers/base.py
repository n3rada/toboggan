from abc import ABC, abstractmethod

# Local imports
from toboggan.core import logbook


class OSHelperBase(ABC):
    """
    Abstract base class for OS-specific operations.
    """

    def __init__(self, executor):
        self._executor = executor
        self._logger = logbook.get_logger()

    @abstractmethod
    def get_current_path(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def create_working_directory_string(self) -> str:
        raise NotImplementedError()
