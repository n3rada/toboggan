# toboggan/core/actions/download/windows.py

# Built-in imports
import base64
import zipfile
from pathlib import Path
import tempfile

# External library imports
from loguru import logger
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils import common
from toboggan.core.utils.transfer import receive_chunks, validate_chunk_size, verify_md5


class DownloadAction(BaseAction):
    """Handles remote file retrieval on Windows systems."""

    DESCRIPTION = "Retrieve a file remotely, compress it, and save it locally."

    def run(
        self, remote_path: str, local_path: str | None = None,
        command_size: int | str | None = None,
    ) -> bool:
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

        # Normalize Windows path
        remote_path = remote_path.replace("/", "\\")

        # Check if the file exists and is accessible
        if self._os_helper.shell_type == "powershell":
            # Use literal path with -LiteralPath to avoid escaping issues
            check_cmd = f'(Test-Path -LiteralPath "{remote_path}" -PathType Leaf).ToString()'
        else:
            check_cmd = f'if exist "{remote_path}" (echo True) else (echo False)'
        try:
            can_read = self._executor.remote_execute(
                command=check_cmd, retry=False, raise_on_failure=True, debug=False,
            ).strip()
        except Exception as exc:
            logger.error(f"Cannot check remote file accessibility: {exc}")
            return False

        if can_read != "True":
            logger.error(f"File not found or not accessible: {remote_path}")
            return False

        logger.info(f"File is accessible: {remote_path}")

        if command_size is None:
            try:
                command_size = self._executor.ensure_command_max_size()
            except Exception as exc:
                logger.error(f"Cannot determine download chunk size: {exc}")
                return False

        # Determine final local path
        local_destination = Path.cwd() if local_path is None else Path(local_path)

        if local_destination.is_dir():
            save_path = local_destination / Path(remote_path).name
        else:
            save_path = local_destination

        logger.info(f"File will be saved to: {save_path}")

        # Step 2: Compress and Base64-encode the remote file
        random_file_name = common.generate_fixed_length_token(6) + ".zip"
        remote_archive = f"{self._executor.working_directory}\\{random_file_name}"
        remote_base64_path = f"{remote_archive}.b64"

        escaped_path = remote_base64_path.replace("'", "''")
        escaped_archive = remote_archive.replace("'", "''")
        cleanup_cmd = (
            f"foreach ($file in @('{escaped_archive}', '{escaped_path}')) {{ "
            "if (Test-Path -LiteralPath $file) { "
            "Remove-Item -LiteralPath $file -Force -ErrorAction Continue } }"
        )
        if self._os_helper.shell_type != "powershell":
            encoded_cleanup = base64.b64encode(cleanup_cmd.encode("utf-16le")).decode()
            cleanup_cmd = f"powershell -nop -EncodedCommand {encoded_cleanup}"

        try:
            logger.info(f"Compressing and encoding file...")

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

            self._executor.remote_execute(
                command=compress_encode_cmd, timeout=60, retry=False, raise_on_failure=True
            )

            # Step 3: Get the encoded file size
            if self._os_helper.shell_type == "powershell":
                size_cmd = f'(Get-Item -LiteralPath "{remote_base64_path}").Length'
            else:
                size_cmd = (
                    f'powershell -nop -c "(Get-Item -LiteralPath \'{remote_base64_path}\').Length"'
                )

            size_output = self._executor.remote_execute(
                command=size_cmd, retry=False, raise_on_failure=True
            ).strip()

            if not size_output or not size_output.isdigit():
                raise ValueError(f"Failed to retrieve encoded file size for: {remote_path}")

            total_encoded_size = int(size_output)
            checksum_cmd = (
                "$md5=[Security.Cryptography.MD5]::Create();"
                f"$f=[IO.File]::OpenRead('{escaped_path}');"
                "try{[BitConverter]::ToString($md5.ComputeHash($f)).Replace('-','')}"
                "finally{$f.Dispose();$md5.Dispose()}"
            )
            if self._os_helper.shell_type != "powershell":
                encoded_checksum = base64.b64encode(
                    checksum_cmd.encode("utf-16le")
                ).decode()
                checksum_cmd = f"powershell -nop -EncodedCommand {encoded_checksum}"
            remote_md5 = self._executor.remote_execute(
                command=checksum_cmd, retry=False, raise_on_failure=True, debug=False,
            ).strip()
            logger.info(
                f"Downloading {remote_path} ({total_encoded_size} encoded bytes, "
                f"initial chunk size {command_size})"
            )

            def read_chunk(offset: int, size: int) -> str:
                if self._os_helper.shell_type == "powershell":
                    chunk_cmd = f"""
    $ProgressPreference='SilentlyContinue'
    $fs = [IO.File]::OpenRead("{remote_base64_path}")
    $fs.Seek({offset}, [IO.SeekOrigin]::Begin) | Out-Null
    $buf = New-Object byte[] {size}
    $read = $fs.Read($buf, 0, {size})
    $fs.Close()
    [Text.Encoding]::ASCII.GetString($buf, 0, $read)
    """.strip()
                else:
                    chunk_cmd = f"""powershell -nop -c "$ProgressPreference='SilentlyContinue'; $fs = [IO.File]::OpenRead('{remote_base64_path}'); $fs.Seek({offset}, [IO.SeekOrigin]::Begin) | Out-Null; $buf = New-Object byte[] {size}; $read = $fs.Read($buf, 0, {size}); $fs.Close(); [Text.Encoding]::ASCII.GetString($buf, 0, $read)" """.strip()
                return self._executor.remote_execute(
                    command=chunk_cmd, timeout=30, retry=False,
                    raise_on_failure=True, debug=False,
                )

            with tempfile.TemporaryDirectory() as temp_dir:
                encoded_path = Path(temp_dir) / "download.b64"
                archive_path = Path(temp_dir) / "download.zip"
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
                encoded_data = encoded_path.read_bytes()
                verify_md5(encoded_data, remote_md5)
                archive_path.write_bytes(base64.b64decode(encoded_data, validate=True))
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(path=local_destination)
            logger.success(f"File downloaded and extracted to: {local_destination}")
            return True
        except Exception as exc:
            logger.error(f"File download failed: {exc}")
            return False
        finally:
            try:
                self._executor.remote_execute(
                    command=cleanup_cmd, retry=False, raise_on_failure=True, debug=False
                )
            except Exception as exc:
                logger.warning(
                    f"Could not remove remote download data "
                    f"{remote_archive}, {remote_base64_path}: {exc}"
                )
