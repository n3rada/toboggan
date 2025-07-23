from pathlib import Path
from typing import Union

# Local library imports
from toboggan.core import logbook
from toboggan.core import executor


class Saver:
    def __init__(self, executor: "executor.Executor"):
        self._executor = executor
        self._logger = logbook.get_logger()

        self._save_directory = Path.cwd() / self._executor.target.hostname
        self._save_directory.mkdir(parents=True, exist_ok=True)
        self._logger.info(f"💾 Save directory initialized at: {self._save_directory}")

    def save(
        self, data: Union[bytes, str], parent_directory: str, filename: str
    ) -> None:
        """
        Save data (text or binary) to a file inside structured target-based path.

        Args:
            data (Union[bytes, str]): Content to write.
            parent_directory (str): Subdirectory under hostname folder.
            filename (str): Final file name.
        """
        base_path = self._save_directory / parent_directory
        try:
            base_path.mkdir(parents=True, exist_ok=True)
            file_path = base_path / filename

            if isinstance(data, bytes):
                file_path.write_bytes(data)
            elif isinstance(data, str):
                file_path.write_text(data)
            else:
                raise ValueError("Unsupported data type for saving")

            self._logger.debug(f"💾 Saved output to: {file_path}")
        except Exception as e:
            self._logger.warning(f"⚠️ Failed to save file {filename}: {e}")
