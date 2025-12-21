# toboggan/core/actions/upload/windows.py

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
    """Handles secure file uploads to a Windows remote system."""

    DESCRIPTION = "Encode and upload a local file to a remote Windows system."

    def run(self, local_path: str, remote_path: str = None):
        """
        Encodes and transfers a local file to a remote Windows system in chunks.

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

        current_working_directory = self._executor.target.pwd.rstrip("\\")

        # Default remote path to current working directory if not provided
        if not remote_path:
            remote_path = f"{current_working_directory}\\{local_file.name}"
        else:
            # Normalize to Windows path
            remote_path = remote_path.replace("/", "\\")

            # Handle relative paths
            if remote_path.startswith(".\\"):
                remote_path = remote_path.lstrip(".\\")

            # If not absolute path, make it relative to current directory
            if not (remote_path[1:3] == ":\\" or remote_path.startswith("\\\\")):
                remote_path = f"{current_working_directory}\\{remote_path}"

            # If remote_path looks like a directory (ends with \), append filename
            if remote_path.endswith("\\"):
                base_path = remote_path.rstrip("\\")
                remote_path = f"{base_path}\\{local_file.name}"

        logger.info(f"📤 Uploading {local_path} to {remote_path}")

        # Define remote encoded path early
        remote_encoded_path = (
            f"{self._executor.working_directory}\\{generate_fixed_length_token(24)}.b64"
        )

        # Clean up any leftover encoded file from previous runs
        self._executor.remote_execute(
            f'Remove-Item -LiteralPath "{remote_encoded_path}" -Force -EA 0',
            retry=False,
        )

        # Step 1: Base64 encode the file
        raw_bytes = local_file.read_bytes()
        encoded_file = base64.b64encode(raw_bytes).decode("utf-8")

        # Calculate local MD5 of original file
        local_md5 = hashlib.md5(raw_bytes).hexdigest().upper()
        logger.info(f"🔒 Local MD5: {local_md5}")

        chunk_size = self._executor.chunk_max_size
        encoded_size = len(encoded_file)
        total_chunks = (encoded_size + chunk_size - 1) // chunk_size

        logger.info(
            f"📦 Encoded file size: {encoded_size} bytes ({total_chunks} chunks)"
        )

        # Step 2: Upload in chunks
        logger.info(
            f"📤 Uploading {local_file.name} in chunks to: {self._executor.working_directory}"
        )

        try:
            with tqdm(
                total=encoded_size, unit="B", unit_scale=True, desc="Uploading"
            ) as progress_bar:
                for idx in range(total_chunks):
                    chunk = encoded_file[idx * chunk_size : (idx + 1) * chunk_size]

                    if self._os_helper.shell_type == "powershell":
                        # Use Add-Content for appending
                        upload_cmd = f'Add-Content -LiteralPath "{remote_encoded_path}" -Value "{chunk}" -NoNewline -EA Stop'
                    else:
                        # CMD: invoke PowerShell
                        # Escape double quotes for CMD
                        escaped_chunk = chunk.replace('"', '`"')
                        upload_cmd = f'powershell -nop -c "Add-Content -LiteralPath \\"{remote_encoded_path}\\" -Value \\"{escaped_chunk}\\" -NoNewline -EA Stop"'

                    self._executor.remote_execute(upload_cmd, timeout=30, debug=False)
                    progress_bar.update(len(chunk))

        except KeyboardInterrupt:
            logger.warning("⚠️ Upload interrupted by user. Cleaning up...")
            self._executor.remote_execute(
                f'Remove-Item -LiteralPath "{remote_encoded_path}" -Force -EA 0',
                retry=False,
            )
            return
        except Exception as exc:
            logger.error(f"❌ Upload failed: {exc}")
            self._executor.remote_execute(
                f'Remove-Item -LiteralPath "{remote_encoded_path}" -Force -EA 0',
                retry=False,
            )
            return

        logger.success(f"📂 Remote encoded file created: {remote_encoded_path}")

        # Step 3: Decode remotely
        logger.info(f"📂 Decoding remotely to {remote_path}")

        if self._os_helper.shell_type == "powershell":
            decode_cmd = f"""
$ProgressPreference='SilentlyContinue'
$enc = [IO.File]::ReadAllText("{remote_encoded_path}")
$bytes = [Convert]::FromBase64String($enc)
[IO.File]::WriteAllBytes("{remote_path}", $bytes)
""".strip()
        else:
            # CMD: invoke PowerShell
            decode_cmd = f"""powershell -nop -c "$ProgressPreference='SilentlyContinue'; $enc = [IO.File]::ReadAllText('{remote_encoded_path}'); $bytes = [Convert]::FromBase64String($enc); [IO.File]::WriteAllBytes('{remote_path}', $bytes)" """.strip()

        result = self._executor.remote_execute(decode_cmd, retry=True, timeout=60)

        # Cleanup encoded file
        self._executor.remote_execute(
            f'Remove-Item -LiteralPath "{remote_encoded_path}" -Force -EA 0',
            retry=False,
        )

        # Step 4: Verify with MD5 checksum
        logger.info("🔍 Verifying file integrity...")

        if self._os_helper.shell_type == "powershell":
            md5_cmd = f'(Get-FileHash -LiteralPath "{remote_path}" -Algorithm MD5).Hash'
        else:
            # CMD: invoke PowerShell
            md5_cmd = f"powershell -nop -c \"(Get-FileHash -LiteralPath '{remote_path}' -Algorithm MD5).Hash\""

        remote_md5 = self._executor.remote_execute(md5_cmd, timeout=30).strip()

        if not remote_md5:
            logger.error(f"❌ Failed to create the file at {remote_path}.")
            return

        logger.info(f"🔒 Remote MD5: {remote_md5}")

        if remote_md5.upper() != local_md5.upper():
            logger.warning("❌ MD5 mismatch!")
            logger.warning("The uploaded file may be corrupted.")
        else:
            logger.success("✅ MD5 checksum matched.")

        logger.success(f"✅ File uploaded successfully: {remote_path}")

        return
