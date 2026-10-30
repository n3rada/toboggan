# Built-in imports
import base64
import hashlib
import ntpath
import re
from pathlib import Path

# External library imports
from loguru import logger
from tqdm import tqdm

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils.common import generate_fixed_length_token
from toboggan.core.utils.transfer import send_chunks, validate_chunk_size


class UploadAction(BaseAction):
    """Encode and upload a local file, verifying writes and the final checksum."""

    DESCRIPTION = "Encode and upload a local file to a Windows remote system."

    def _command(self, script: str) -> str:
        if self._os_helper.shell_type == "powershell":
            return script
        # EncodedCommand requires UTF-16LE, including when invoked from CMD.
        # https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        return f"powershell -nop -EncodedCommand {encoded}"

    def run(
        self, local_path: str, remote_path: str | None = None,
        command_size: int | str | None = None,
    ) -> bool:
        """Upload using the session size or a per-transfer command-size override."""
        local_file = Path(local_path)
        if not local_file.is_file():
            logger.error(f"Local file does not exist: {local_path}")
            return False
        try:
            limit = validate_chunk_size(
                self._executor.ensure_command_max_size()
                if command_size is None else command_size
            )
            raw_bytes = local_file.read_bytes()
        except Exception as exc:
            logger.error(f"Cannot prepare upload: {exc}")
            return False

        directory = self._executor.target.pwd
        if not remote_path:
            remote_path = ntpath.join(directory, local_file.name)
        else:
            remote_path = remote_path.replace("/", "\\")
            if not ntpath.isabs(remote_path):
                remote_path = ntpath.join(directory, remote_path)
            if remote_path.endswith("\\"):
                remote_path += local_file.name

        remote_encoded_path = ntpath.join(
            self._executor.working_directory, generate_fixed_length_token(24) + ".b64"
        )
        staged = "'" + remote_encoded_path.replace("'", "''") + "'"
        destination = "'" + remote_path.replace("'", "''") + "'"
        encoded_file = base64.b64encode(raw_bytes).decode("ascii")
        local_md5 = hashlib.md5(raw_bytes).hexdigest()

        def make_command(offset: int, chunk: str) -> str:
            # Truncate unacknowledged bytes before retrying the same offset.
            # https://learn.microsoft.com/en-us/dotnet/api/system.io.filestream.setlength
            return self._command(
                "$ErrorActionPreference='Stop';"
                f"$f=[IO.File]::OpenWrite({staged});"
                f"try{{$f.SetLength({offset});$f.Position={offset};"
                f"$b=[Text.Encoding]::ASCII.GetBytes('{chunk}');"
                "$f.Write($b,0,$b.Length);$f.Length}finally{$f.Dispose()}"
            )

        decode_cmd = self._command(
            "$ErrorActionPreference='Stop';"
            f"$b=[Convert]::FromBase64String([IO.File]::ReadAllText({staged}));"
            f"[IO.File]::WriteAllBytes({destination},$b)"
        )
        checksum_cmd = self._command(
            "$ErrorActionPreference='Stop';"
            "$md5=[Security.Cryptography.MD5]::Create();"
            f"$f=[IO.File]::OpenRead({destination});"
            "try{[BitConverter]::ToString($md5.ComputeHash($f)).Replace('-','')}"
            "finally{$f.Dispose();$md5.Dispose()}"
        )
        cleanup_cmd = self._command(
            f"if(Test-Path -LiteralPath {staged}){{"
            f"Remove-Item -LiteralPath {staged} -Force -ErrorAction Stop}}"
        )
        if any(
            len(command.encode("utf-8")) > limit
            for command in (make_command(0, ""), decode_cmd, checksum_cmd, cleanup_cmd)
        ):
            logger.error("Command size is too small for the upload command overhead.")
            return False

        def execute(command: str) -> str:
            return self._executor.remote_execute(
                command, timeout=30, retry=False, raise_on_failure=True, debug=False
            )

        logger.info(
            f"Uploading {local_path} to {remote_path} "
            f"({len(encoded_file)} encoded bytes, command limit {limit})."
        )
        try:
            with tqdm(
                total=len(encoded_file), unit="B", unit_scale=True, desc="Uploading",
                disable=logger._core.min_level <= logger.level("TRACE").no,
            ) as progress:
                send_chunks(execute, make_command, encoded_file, limit, progress.update)
            self._executor.remote_execute(
                decode_cmd, timeout=60, retry=False, raise_on_failure=True
            )
            remote_md5 = execute(checksum_cmd).strip()
            if not re.fullmatch(r"[0-9a-fA-F]{32}", remote_md5):
                raise ValueError("Remote file checksum unavailable or invalid.")
            if remote_md5.lower() != local_md5:
                raise ValueError("MD5 mismatch; the uploaded file may be corrupted.")
            logger.success(f"File uploaded and checksum verified: {remote_path}")
            return True
        except KeyboardInterrupt:
            logger.warning("Upload interrupted; cleaning up staged data.")
            return False
        except Exception as exc:
            logger.error(f"Upload failed: {exc}")
            return False
        finally:
            try:
                output = execute(cleanup_cmd).strip()
                if output:
                    logger.warning(
                        f"Cleanup of {remote_encoded_path} returned: {output}"
                    )
            except Exception as exc:
                logger.warning(
                    f"Could not remove staged upload {remote_encoded_path}: {exc}"
                )
