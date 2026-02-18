# toboggan/core/actions/upload/linux.py

# Standard library imports
import base64
import hashlib
from pathlib import Path

# Related third-party imports
from loguru import logger
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils.common import generate_fixed_length_token


class UploadAction(BaseAction):
    """Handles secure file uploads to a remote system."""

    DESCRIPTION = "Compress, encode, and upload a local file to a remote system."

    def run(self, local_path: str, remote_path: str = None):
        """
        Compresses, encodes, and transfers a local file to a remote system in chunks.

        Args:
            local_path (str): Path to the local file.
            remote_path (str, optional): Destination path on the remote system.
                                         Can be a directory or full file path.
                                         Defaults to the current working directory.
        """
        local_file = Path(local_path)
        if not local_file.exists() or not local_file.is_file():
            logger.error(f"❌ Local file does not exist: {local_path}")
            return

        current_working_directory = self._executor.target.pwd.rstrip("/")

        # Default remote path to current working directory if not provided
        if not remote_path:
            remote_path = f"{current_working_directory}/{local_file.name}"
        else:

            if remote_path.startswith("./"):
                remote_path = remote_path.lstrip("./")

            if not remote_path.startswith("/"):
                remote_path = f"{current_working_directory}/{remote_path}"

            # If remote_path looks like a directory (ends with /), append filename
            if remote_path.endswith("/"):
                remote_path = f"{remote_path.rstrip('/')}/{local_file.name}"

        logger.info(f"📤 Uploading {local_path} to {remote_path}")

        # Define remote encoded path early
        remote_encoded_path = (
            f"{self._executor.working_directory}/{generate_fixed_length_token(24)}"
        )

        # Clean up any leftover encoded file from previous runs
        self._executor.remote_execute(f"rm -f {remote_encoded_path}")

        # Step 1: Compress & base64 encode the file
        raw_bytes = local_file.read_bytes()
        encoded_file = base64.b64encode(raw_bytes).decode("utf-8")

        # Calculate local MD5 of original file
        local_md5 = hashlib.md5(raw_bytes).hexdigest()
        logger.info(f"🔒 Local MD5: {local_md5}")

        # Calculate effective chunk size accounting for command overhead
        # Command format: printf %s {chunk} >> {remote_encoded_path}
        command_overhead = len("printf %s ") + len(" >> ") + len(remote_encoded_path)
        chunk_size = max(1, self._executor.chunk_max_size - command_overhead)

        encoded_size = len(encoded_file)
        total_chunks = (encoded_size + chunk_size - 1) // chunk_size

        logger.info(
            f"📦 Encoded file size: {encoded_size} bytes ({total_chunks} chunks, {chunk_size}B each)"
        )

        # Step 2: Upload in chunks
        logger.info(
            f"📤 Uploading {local_file.name} in chunks inside: {self._executor.working_directory}"
        )

        # Disable progress bar when trace logging is enabled to avoid polluting output
        use_progress_bar = logger._core.min_level > logger.level("TRACE").no

        try:
            if use_progress_bar:
                with tqdm(
                    total=encoded_size, unit="B", unit_scale=True, desc="Uploading"
                ) as progress_bar:
                    for idx in range(total_chunks):
                        chunk = encoded_file[idx * chunk_size : (idx + 1) * chunk_size]
                        self._executor.remote_execute(
                            f"printf %s {chunk} >> {remote_encoded_path}"
                        )
                        progress_bar.update(len(chunk))
            else:
                for idx in range(total_chunks):
                    chunk = encoded_file[idx * chunk_size : (idx + 1) * chunk_size]
                    self._executor.remote_execute(
                        f"printf %s {chunk} >> {remote_encoded_path}"
                    )
        except KeyboardInterrupt:
            logger.warning("⚠️ Upload interrupted by user. Cleaning up...")
            self._executor.remote_execute(f"rm -f {remote_encoded_path}")
            return

        logger.success(f"📂 Remote encoded file path: {remote_encoded_path}")

        # Step 3: Decode and decompress remotely
        logger.info(f"📂 Decoding and extracting remotely to {remote_path}")
        base64_path = self._executor.os_helper.get_command_location("base64")
        self._executor.remote_execute(
            f"{base64_path} -d {remote_encoded_path}|dd of={remote_path} bs=1024",
            retry=True,
            timeout=60,
        )

        self._executor.remote_execute(f"rm -f {remote_encoded_path}")

        # Check if the file was created successfully
        md5sum_path = self._executor.os_helper.get_command_location("md5sum")
        md5sum = self._executor.remote_execute(f"{md5sum_path} {remote_path}").strip()

        if not md5sum:
            logger.error(f"❌ Failed to create the file at {remote_path}.")
            return

        remote_md5 = md5sum.split()[0]
        logger.info(f"🔒 Remote MD5: {remote_md5}")
        if remote_md5 != local_md5:
            logger.warning("❌ MD5 mismatch!")
            logger.warning("The uploaded file may be corrupted.")
        else:
            logger.success("✅ MD5 checksum matched.")

        logger.success(f"✅ File uploaded: {remote_path}")

        return
