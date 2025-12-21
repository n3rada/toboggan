# toboggan/core/actions/download/linux.py

# Standard library imports
import base64
import tarfile
from pathlib import Path
import tempfile

# Third party library imports
from loguru import logger
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils import common


class DownloadAction(BaseAction):
    """Handles remote file retrieval."""

    DESCRIPTION = "Retrieve a file remotely, compress it, and save it locally."

    def run(self, remote_path: str, local_path: str = None, chunk_size: int = 4096):
        """
        Attempts to compress, encode, and retrieve a remote file in chunks, saving it locally.

        Args:
            remote_path (str): Path to the remote file.
            local_path (str, optional): Path where the file should be saved. If a directory, saves inside.
                                        If None, saves in the current working directory.
            chunk_size (int, optional): Size of each chunk to be retrieved. Defaults to 4096.

        Returns:
            bool: True if the file was successfully downloaded and extracted, False otherwise.
        """

        # Check if the file is readable
        can_read = self._executor.remote_execute(
            command=f"test -r {remote_path} && echo R || echo U"
        ).strip()

        if can_read != "R":
            logger.error(f"❌ No read permission for {remote_path}.")
            return

        logger.info(f"📂 File is accessible: {remote_path}")

        # Determine final local path
        if local_path is None:
            local_path = Path.cwd()
        else:
            local_path = Path(local_path)

        if local_path.is_dir():
            save_path = local_path / Path(remote_path).name
        else:
            save_path = local_path

        logger.info(f"💾 File will be saved to: {save_path}")

        # Step 2: Compress and Base64-encode the remote file
        random_file_name = common.generate_fixed_length_token(6) + ".tar.gz"
        remote_archive = f"{self._executor.working_directory}/{random_file_name}"
        remote_base64_path = f"{remote_archive}.b64"

        # Tar and encode
        tar_path = self._executor.os_helper.get_command_location("tar")
        base64_path = self._executor.os_helper.get_command_location("base64")
        self._executor.remote_execute(
            command=f"{tar_path} czf - {remote_path} | {base64_path} -w0 > {remote_base64_path}"
        )

        # Step 3: Get the encoded file size
        wc_output = self._executor.remote_execute(
            command=f"wc -c {remote_base64_path}"
        ).strip()
        if not wc_output:
            logger.error(f"❌ Failed to retrieve file size for: {remote_path}")
            self._executor.remote_execute(command=f"rm -f {remote_base64_path}")
            return False

        total_encoded_size = int(wc_output.split()[0])
        total_chunks = (total_encoded_size + chunk_size - 1) // chunk_size

        logger.info(
            f"⬇️ Downloading {remote_path} ({total_chunks} chunks) to {save_path}.tar.gz"
        )

        # Step 4: Download in chunks
        temp_download_path = tempfile.mktemp(suffix=".b64")
        with (
            open(temp_download_path, "wb") as temp_file,
            tqdm(
                total=total_encoded_size, unit="B", unit_scale=True, desc="Downloading"
            ) as progress_bar,
        ):
            for idx in range(total_chunks):
                offset = idx * chunk_size
                chunk = self._executor.remote_execute(
                    command=f"dd if={remote_base64_path} bs=1 skip={offset} count={chunk_size} 2>/dev/null"
                ).strip()

                if chunk:
                    try:
                        temp_file.write(chunk.encode())
                        progress_bar.update(len(chunk))
                    except Exception as exc:
                        logger.warning(f"⚠️ Error writing chunk {idx + 1}: {exc}")
                else:
                    logger.warning(f"⚠️ Missing chunk {idx + 1}, skipping.")

        # Step 5: Decode and extract
        self._executor.remote_execute(command=f"rm -f {remote_base64_path}")

        try:
            decoded_data = base64.b64decode(Path(temp_download_path).read_bytes())
            temp_tar_path = temp_download_path.replace(".b64", ".tar.gz")
            with open(temp_tar_path, "wb") as tar_file:
                tar_file.write(decoded_data)

            # Extract contents
            with tarfile.open(temp_tar_path, "r:gz") as tar:
                tar.extractall(path=local_path)

            logger.success(f"✅ File download and extraction completed: {local_path}")
        except Exception as exc:
            logger.error(f"❌ Failed to decode and extract file: {exc}")
            return
        finally:
            Path(temp_download_path).unlink(missing_ok=True)
            Path(temp_tar_path).unlink(missing_ok=True)

        return
