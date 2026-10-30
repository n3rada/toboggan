# toboggan/core/actions/download/linux.py

# Standard library imports
import base64
import shlex
import tarfile
from pathlib import Path
import tempfile

# Third party library imports
from loguru import logger
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils import common
from toboggan.core.utils.transfer import receive_chunks, validate_chunk_size


class DownloadAction(BaseAction):
    """Handles remote file retrieval."""

    DESCRIPTION = "Retrieve a file remotely, compress it, and save it locally."

    def run(self, remote_path: str, local_path: str = None, command_size: int = None):
        """
        Attempts to compress, encode, and retrieve a remote file in chunks, saving it locally.

        Args:
            remote_path (str): Path to the remote file.
            local_path (str, optional): Path where the file should be saved. If a directory, saves inside.
                                        If None, saves in the current working directory.
            command_size (int, optional): Initial chunk size. Defaults to the executor's
                                         command_max_size; reduced if responses are short.

        Returns:
            bool: True if the file was successfully downloaded and extracted, False otherwise.
        """

        try:
            if command_size is not None:
                command_size = validate_chunk_size(command_size)
        except ValueError as exc:
            logger.error(str(exc))
            return False

        # Check if the file is readable
        can_read = self._executor.remote_execute(
            command=f"test -r {shlex.quote(remote_path)} && echo R || echo U"
        ).strip()

        if can_read != "R":
            logger.error(f"No read permission for {remote_path}.")
            return False

        logger.info(f"File is accessible: {remote_path}")

        if command_size is None:
            try:
                command_size = self._executor.ensure_command_max_size()
            except Exception as exc:
                logger.error(f"Cannot determine download chunk size: {exc}")
                return False

        # Determine final local path
        if local_path is None:
            local_path = Path.cwd()
        else:
            local_path = Path(local_path)

        if local_path.is_dir():
            save_path = local_path / Path(remote_path).name
        else:
            save_path = local_path

        logger.info(f"File will be saved to: {save_path}")

        # Step 2: Compress and Base64-encode the remote file
        random_file_name = common.generate_fixed_length_token(6) + ".tar.gz"
        remote_archive = f"{self._executor.working_directory}/{random_file_name}"
        remote_base64_path = f"{remote_archive}.b64"

        commands = {
            name: self._os_helper.get_command_location(name)
            for name in ("tar", "base64", "wc", "dd", "rm")
        }
        missing = [name for name, command in commands.items() if not command]
        if missing:
            logger.error(f"Required download commands unavailable: {', '.join(missing)}")
            return False
        encoded_remote = shlex.quote(remote_base64_path)

        def read_chunk(offset: int, size: int) -> str:
            return self._executor.remote_execute(
                command=(
                    f"{commands['dd']} if={encoded_remote} bs=1 skip={offset} "
                    f"count={size} 2>/dev/null"
                ),
                timeout=30, retry=False, raise_on_failure=True, debug=False,
            )

        try:
            self._executor.remote_execute(
                command=(
                    f"{commands['tar']} czf - {shlex.quote(remote_path)} | "
                    f"{commands['base64']} -w0 > {encoded_remote}"
                ),
                timeout=60, retry=False, raise_on_failure=True,
            )
            wc_output = self._executor.remote_execute(
                command=f"{commands['wc']} -c < {encoded_remote}",
                retry=False, raise_on_failure=True,
            ).strip()
            if not wc_output or not wc_output.split()[0].isdigit():
                raise ValueError(f"Failed to retrieve file size for: {remote_path}")
            total_encoded_size = int(wc_output.split()[0])
            logger.info(
                f"Downloading {remote_path} ({total_encoded_size} encoded bytes, "
                f"initial chunk size {command_size}) to {save_path}.tar.gz"
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                encoded_path = Path(temp_dir) / "download.b64"
                archive_path = Path(temp_dir) / "download.tar.gz"
                with (
                    encoded_path.open("wb") as temp_file,
                    tqdm(
                        total=total_encoded_size, unit="B", unit_scale=True,
                        desc="Downloading",
                    ) as progress_bar,
                ):
                    receive_chunks(
                        read_chunk, temp_file, total_encoded_size, command_size,
                        progress_bar.update,
                    )
                archive_path.write_bytes(
                    base64.b64decode(encoded_path.read_bytes(), validate=True)
                )
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(path=local_path)
            logger.success(f"File download and extraction completed: {local_path}")
            return True
        except Exception as exc:
            logger.error(f"File download failed: {exc}")
            return False
        finally:
            try:
                self._executor.remote_execute(
                    command=f"{commands['rm']} -f {encoded_remote}",
                    retry=False, raise_on_failure=True, debug=False
                )
            except Exception as exc:
                logger.warning(
                    f"Could not remove remote download data {remote_base64_path}: {exc}"
                )
