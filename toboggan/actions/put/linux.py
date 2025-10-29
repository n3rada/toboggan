# Standard library imports
import base64
import hashlib
from pathlib import Path

# Related third-party imports
from loguru import logger
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
            logger.error(f"❌ Local file does not exist: {local_path}")
            return

        # Default remote path to current working directory if not provided
        if not remote_path:
            remote_path = f"{self._executor.target.pwd}/{local_file.name}"

        logger.info(f"📤 Uploading {local_path} to {remote_path}")

        # Define remote encoded path early
        remote_encoded_path = (
            f"{self._executor.working_directory}/{local_file.name}.b64"
        )

        # Clean up any leftover encoded file from previous runs
        self._executor.remote_execute(f"rm -f {remote_encoded_path}")

        # Ensure remote path is writable
        upper_directory = Path(remote_path).parent

        test_file = f"{upper_directory}/{generate_fixed_length_token(5)}"

        test_command = f"touch {test_file} && echo O && rm -f {test_file} || echo F"

        if self._executor.remote_execute(test_command) != "O":
            logger.error(
                f"❌ Cannot write to remote directory: {upper_directory}. "
                "Please check permissions or specify a different path."
            )
            return

        # Step 1: Compress & base64 encode the file
        raw_bytes = local_file.read_bytes()
        encoded_file = base64.b64encode(raw_bytes).decode("utf-8")

        # Calculate local MD5 of original file
        local_md5 = hashlib.md5(raw_bytes).hexdigest()
        logger.info(f"🔒 Local MD5: {local_md5}")

        chunk_size = self._executor.chunk_max_size
        encoded_size = len(encoded_file)
        total_chunks = (encoded_size + chunk_size - 1) // chunk_size

        logger.info(
            f"📦 Encoded file size: {encoded_size} bytes ({total_chunks} chunks)"
        )

        # Step 2: Upload in chunks
        logger.info(
            f"📤 Uploading {local_file.name} in chunks inside: {self._executor.working_directory}"
        )

        try:
            with tqdm(
                total=encoded_size, unit="B", unit_scale=True, desc="Uploading"
            ) as progress_bar:
                for idx in range(total_chunks):
                    chunk = encoded_file[idx * chunk_size : (idx + 1) * chunk_size]
                    self._executor.remote_execute(
                        f"echo -n {chunk} >> {remote_encoded_path}"
                    )
                    progress_bar.update(len(chunk))
        except KeyboardInterrupt:
            logger.warning("⚠️ Upload interrupted by user. Cleaning up...")
            self._executor.remote_execute(f"rm -f {remote_encoded_path}")
            return

        logger.success(f"📂 Remote encoded file path: {remote_encoded_path}")

        # Step 3: Decode and decompress remotely
        logger.info(f"📂 Decoding and extracting remotely to {remote_path}")
        self._executor.remote_execute(
            f"base64 -d {remote_encoded_path} | dd of={remote_path} bs=1024",
            retry=True,
            timeout=60,
        )

        self._executor.remote_execute(f"rm -f {remote_encoded_path}")

        # Check if the file was created successfully
        md5sum = self._executor.remote_execute(f"md5sum {remote_path}").strip()

        if not md5sum:
            logger.error(f"❌ Failed to create the file at {remote_path}.")
            return

        remote_md5 = md5sum.split()[0]
        logger.info(f"🔒 Remote MD5: {remote_md5}")
        if remote_md5 != local_md5:
            logger.warning(f"❌ MD5 mismatch!")
            return

        logger.success(f"✅ File uploaded and extracted successfully: {remote_path}")

        return remote_path
