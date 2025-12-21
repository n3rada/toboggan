# toboggan/core/actions/download/windows.py

# Standard library imports
import base64
import zipfile
from pathlib import Path
import tempfile

# Third party library imports
from loguru import logger
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils import common


class DownloadAction(BaseAction):
    """Handles remote file retrieval on Windows systems."""

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

        # Normalize Windows path
        remote_path = remote_path.replace("/", "\\")

        # Check if the file exists and is accessible
        if self._os_helper.shell_type == "powershell":
            # Use literal path with -LiteralPath to avoid escaping issues
            can_read = self._executor.remote_execute(
                command=f'(Test-Path -LiteralPath "{remote_path}" -PathType Leaf).ToString()'
            ).strip()
        else:
            can_read = self._executor.remote_execute(
                command=f'if exist "{remote_path}" (echo True) else (echo False)'
            ).strip()

        if "True" not in can_read:
            logger.error(f"❌ File not found or not accessible: {remote_path}")
            return False

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
        random_file_name = common.generate_fixed_length_token(6) + ".zip"
        remote_archive = f"{self._executor.working_directory}\\{random_file_name}"
        remote_base64_path = f"{remote_archive}.b64"

        logger.info(f"🗜️ Compressing and encoding file...")

        if self._os_helper.shell_type == "powershell":
            # Use PowerShell's Compress-Archive and Base64 encoding
            # Use double quotes and escape any internal quotes
            compress_encode_cmd = f"""
$ProgressPreference='SilentlyContinue'
$src = "{remote_path}"
$zip = "{remote_archive}"
$b64 = "{remote_base64_path}"
Compress-Archive -LiteralPath $src -DestinationPath $zip -Force
$bytes = [IO.File]::ReadAllBytes($zip)
$enc = [Convert]::ToBase64String($bytes)
[IO.File]::WriteAllText($b64, $enc)
Remove-Item -LiteralPath $zip -Force
""".strip()
        else:
            # CMD: invoke PowerShell - escape quotes properly
            compress_encode_cmd = f"""powershell -nop -c "$ProgressPreference='SilentlyContinue'; $src = '{remote_path}'; $zip = '{remote_archive}'; $b64 = '{remote_base64_path}'; Compress-Archive -LiteralPath $src -DestinationPath $zip -Force; $bytes = [IO.File]::ReadAllBytes($zip); $enc = [Convert]::ToBase64String($bytes); [IO.File]::WriteAllText($b64, $enc); Remove-Item -LiteralPath $zip -Force" """.strip()

        result = self._executor.remote_execute(
            command=compress_encode_cmd, timeout=60, retry=False
        )

        # Step 3: Get the encoded file size
        if self._os_helper.shell_type == "powershell":
            size_cmd = f'(Get-Item -LiteralPath "{remote_base64_path}").Length'
        else:
            size_cmd = (
                f'powershell -nop -c "(Get-Item -LiteralPath \'{remote_base64_path}\').Length"'
            )

        size_output = self._executor.remote_execute(command=size_cmd).strip()

        if not size_output or not size_output.isdigit():
            logger.error(f"❌ Failed to retrieve encoded file size for: {remote_path}")
            self._executor.remote_execute(
                command=f'Remove-Item -LiteralPath "{remote_base64_path}" -Force -EA 0'
            )
            return False

        total_encoded_size = int(size_output)
        total_chunks = (total_encoded_size + chunk_size - 1) // chunk_size

        logger.info(
            f"⬇️ Downloading {remote_path} ({total_chunks} chunks, {total_encoded_size} bytes)"
        )

        # Step 4: Download in chunks
        temp_file_obj = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".b64", delete=False
        )
        temp_download_path = temp_file_obj.name

        with (
            temp_file_obj as temp_file,
            tqdm(
                total=total_encoded_size, unit="B", unit_scale=True, desc="Downloading"
            ) as progress_bar,
        ):
            for idx in range(total_chunks):
                offset = idx * chunk_size

                if self._os_helper.shell_type == "powershell":
                    # Read chunk using .NET methods for reliability
                    chunk_cmd = f"""
$ProgressPreference='SilentlyContinue'
$fs = [IO.File]::OpenRead("{remote_base64_path}")
$fs.Seek({offset}, [IO.SeekOrigin]::Begin) | Out-Null
$buf = New-Object byte[] {chunk_size}
$read = $fs.Read($buf, 0, {chunk_size})
$fs.Close()
[Text.Encoding]::ASCII.GetString($buf, 0, $read)
""".strip()
                else:
                    # CMD: invoke PowerShell
                    chunk_cmd = f"""powershell -nop -c "$ProgressPreference='SilentlyContinue'; $fs = [IO.File]::OpenRead('{remote_base64_path}'); $fs.Seek({offset}, [IO.SeekOrigin]::Begin) | Out-Null; $buf = New-Object byte[] {chunk_size}; $read = $fs.Read($buf, 0, {chunk_size}); $fs.Close(); [Text.Encoding]::ASCII.GetString($buf, 0, $read)" """.strip()

                chunk = self._executor.remote_execute(
                    command=chunk_cmd, timeout=30, retry=False, debug=False
                ).strip()

                if chunk:
                    try:
                        temp_file.write(chunk.encode("ascii"))
                        progress_bar.update(len(chunk))
                    except Exception as exc:
                        logger.warning(f"⚠️ Error writing chunk {idx + 1}: {exc}")
                else:
                    logger.warning(f"⚠️ Missing chunk {idx + 1}, skipping.")

        # Step 5: Cleanup remote files
        self._executor.remote_execute(
            command=f'Remove-Item -LiteralPath "{remote_base64_path}" -Force -EA 0',
            retry=False,
        )

        # Step 6: Decode and extract
        try:
            logger.info("🔓 Decoding and extracting...")
            decoded_data = base64.b64decode(Path(temp_download_path).read_text())
            temp_zip_path = temp_download_path.replace(".b64", ".zip")

            with open(temp_zip_path, "wb") as zip_file:
                zip_file.write(decoded_data)

            # Extract contents
            with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                zip_ref.extractall(path=local_path)

            logger.success(f"✅ File downloaded and extracted to: {local_path}")
            return True

        except Exception as exc:
            logger.error(f"❌ Failed to decode and extract file: {exc}")
            return False

        finally:
            Path(temp_download_path).unlink(missing_ok=True)
            if "temp_zip_path" in locals():
                Path(temp_zip_path).unlink(missing_ok=True)
