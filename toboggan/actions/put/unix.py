# Standard library imports
import base64
import gzip
from pathlib import Path

# Related third-party imports
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.utils.methods import generate_fixed_length_token


class PutAction(BaseAction):
    """Handles secure file uploads to a remote system."""

    DESCRIPTION = "Compress, encode, and upload a local file to a remote system."

    def run(self, local_path: str, remote_path: str = None):
        """
        Compresses, encodes, and transfers a local file to a remote system in chunks.

        Args:
            local_path (str): Path to the local file.
            remote_path (str, optional): Destination path on the remote system.
                                         Defaults to the current working directory.
        """
        local_file = Path(local_path)
        if not local_file.exists() or not local_file.is_file():
            self._logger.error(f"❌ Local file does not exist: {local_path}")
            return

        # Default remote path to current working directory if not provided
        if not remote_path:
            remote_path = f"{self._executor.target.pwd}/{local_file.name}"

        self._logger.info(f"📤 Uploading {local_path} to {remote_path}")

        # Ensure remote path is writable
        upper_directory = Path(remote_path).parent

        test_file = f"{upper_directory}/{generate_fixed_length_token(5)}"

        test_command = f"touch {test_file} && echo O && rm -f {test_file} || echo F"

        if self._executor.remote_execute(test_command) != "O":
            self._logger.error(
                f"❌ Cannot write to remote directory: {upper_directory}. "
                "Please check permissions or specify a different path."
            )
            return

        # Step 1: Compress & base64 encode the file
        compressed_data = gzip.compress(local_file.read_bytes())
        encoded_file = base64.b64encode(compressed_data).decode("utf-8")

        chunk_size = self._executor.chunk_max_size

        encoded_size = len(encoded_file)
        total_chunks = (encoded_size + chunk_size - 1) // chunk_size

        self._logger.info(
            f"📦 Encoded file size: {encoded_size} bytes ({total_chunks} chunks)"
        )

        # Step 2: Upload in chunks
        remote_encoded_path = (
            f"{self._executor.working_directory}/{local_file.name}.gz.b64"
        )

        with tqdm(
            total=encoded_size, unit="B", unit_scale=True, desc="Uploading"
        ) as progress_bar:
            for idx in range(total_chunks):
                chunk = encoded_file[idx * chunk_size : (idx + 1) * chunk_size]
                self._executor.remote_execute(
                    f"echo -n '{chunk}' >> {remote_encoded_path}"
                )
                progress_bar.update(len(chunk))

        # Step 3: Decode and decompress remotely
        self._logger.info(f"📂 Decoding and extracting remotely: {remote_path}")
        self._executor.remote_execute(
            f"base64 -d {remote_encoded_path} | gunzip -c | dd of={remote_path} bs=1"
        )

        # Step 4: Cleanup
        self._executor.remote_execute(f"rm -f {remote_encoded_path}")
        self._logger.success(
            f"✅ File uploaded and extracted successfully: {remote_path}"
        )

        return remote_path
