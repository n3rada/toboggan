from pathlib import Path

from toboggan.core.action import BaseAction
from toboggan.actions.put.linux import PutAction


class DropBinary(BaseAction):
    DESCRIPTION = "Upload a binary to the target and make it executable."

    def run(self, local_path: str = None, remote_path: str = None) -> None:
        if not local_path:
            self._logger.error("❌ You must provide a local path to the binary.")
            return

        local_path = Path(local_path).expanduser()

        # Sanity check
        if not local_path.exists() or not local_path.is_file():
            self._logger.error(f"❌ Local binary not found: {local_path}")
            return

        filename = local_path.name

        # If remote path ends with '/', it's probably a directory
        if remote_path and remote_path.endswith("/"):
            self._logger.error(
                "❌ remote_path must be a full file path, not a directory."
            )
            return

        if not remote_path:
            self._logger.info("📌 No remote path provided, using working directory.")
            remote_path = f"{self._executor.working_directory}/{filename}"

        # Upload
        if PutAction(self._executor).run(
            local_path=str(local_path), remote_path=remote_path
        ):
            chmod_result = self._executor.remote_execute(f"chmod +x {remote_path}")
            if chmod_result is not None:
                self._logger.success(f"✅ {filename} made executable.")
            else:
                self._logger.warning(f"⚠️ Failed to chmod {filename}")
