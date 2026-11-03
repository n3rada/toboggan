# toboggan/core/actions/drop_bin/linux.py

# Standard library imports
from pathlib import Path
import posixpath
import shlex

# External library imports
from loguru import logger

# Local library imports
from toboggan.core.action import BaseAction
from toboggan.core.actions.upload.linux import UploadAction


class DropBinary(BaseAction):
    DESCRIPTION = "Upload a binary to the target and make it executable."

    def run(self, local_path: str = None, remote_path: str = None) -> bool:
        if not local_path:
            logger.error("You must provide a local path to the binary.")
            return False

        local_path = Path(local_path).expanduser()

        # Sanity check
        if not local_path.exists() or not local_path.is_file():
            logger.error(f"Local binary not found: {local_path}")
            return False

        filename = local_path.name

        # If remote path ends with '/', it's probably a directory
        if remote_path and remote_path.endswith("/"):
            logger.error("remote_path must be a full file path, not a directory.")
            return False

        if not remote_path:
            logger.info("No remote path provided, using working directory.")
            remote_path = f"{self._executor.working_directory}/{filename}"
        elif not posixpath.isabs(remote_path):
            remote_path = posixpath.join(self._executor.target.pwd, remote_path)

        # Upload
        if not UploadAction(self._executor).run(
            local_path=str(local_path), remote_path=remote_path
        ):
            return False

        chmod = self._os_helper.get_command_location("chmod")
        if not chmod:
            logger.error(f"Cannot make dropped binary executable: {remote_path}")
            return False
        try:
            self._executor.remote_execute(
                f"{chmod} +x {shlex.quote(remote_path)}",
                retry=False, raise_on_failure=True, debug=False,
            )
        except Exception as exc:
            logger.error(f"Cannot make dropped binary executable: {exc}")
            return False
        logger.success(f"{filename} made executable: {remote_path}")
        return True
