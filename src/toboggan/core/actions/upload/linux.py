import base64
import hashlib
import posixpath
import re
import shlex
from pathlib import Path

from loguru import logger
from tqdm import tqdm

from toboggan.core.action import BaseAction
from toboggan.core.utils.common import generate_fixed_length_token
from toboggan.core.utils.transfer import send_chunks, validate_chunk_size


class UploadAction(BaseAction):
    """Encode and upload a local file, verifying writes and the final checksum."""

    DESCRIPTION = "Encode and upload a local file to a remote system."

    def run(
        self, local_path: str, remote_path: str = None, command_size: int = None
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
            remote_path = posixpath.join(directory, local_file.name)
        else:
            if not posixpath.isabs(remote_path):
                remote_path = posixpath.join(directory, remote_path)
            if remote_path.endswith("/"):
                remote_path += local_file.name

        commands = {
            name: self._os_helper.get_command_location(name)
            for name in ("dd", "wc", "base64", "md5sum", "rm")
        }
        missing = [name for name, command in commands.items() if not command]
        if missing:
            logger.error(f"Required upload commands unavailable: {', '.join(missing)}")
            return False

        remote_encoded_path = (
            f"{self._executor.working_directory}/{generate_fixed_length_token(24)}"
        )
        staged = shlex.quote(remote_encoded_path)
        destination = shlex.quote(remote_path)
        encoded_file = base64.b64encode(raw_bytes).decode("ascii")
        local_md5 = hashlib.md5(raw_bytes).hexdigest()

        def make_command(offset: int, chunk: str) -> str:
            # Without conv=notrunc, dd discards any old tail beyond the seek offset.
            return (
                f"printf %s '{chunk}' | {commands['dd']} of={staged} "
                f"bs=1 seek={offset} 2>/dev/null && {commands['wc']} -c < {staged}"
            )

        decode_cmd = f"{commands['base64']} -d {staged} > {destination}"
        checksum_cmd = f"{commands['md5sum']} {destination}"
        cleanup_cmd = f"{commands['rm']} -f {staged}"
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
            checksum = execute(checksum_cmd).strip()
            remote_md5 = checksum.split()[0] if checksum else ""
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
