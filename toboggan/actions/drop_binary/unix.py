from pathlib import Path
from toboggan.core.action import BaseAction
from toboggan.actions.put.unix import PutAction


class DropBinary(BaseAction):
    DESCRIPTION = "Upload a binary to the target and make it executable."

    def run(self, local_path: str = None, remote_path: str = None) -> None:
        if not local_path:
            self._logger.warning("No binary path provided.")
            return

        local_path = Path(local_path).resolve()

        if not local_path.exists() or not local_path.is_file():
            self._logger.warning(f"⚠️ File not found: {local_path}")
            return

        filename = local_path.name

        if not remote_path:
            self._logger.info(
                "No remote path provided, using current working directory."
            )
            remote_path = f"{self._executor.working_directory}/{filename}"

        if (
            PutAction(self._executor).run(
                local_path=str(local_path), remote_path=remote_path
            )
            is not None
        ):

            chmod_result = self._executor.remote_execute(f"chmod +x {remote_path}")
            if chmod_result is not None:
                self._logger.success(f"✅ {filename} made executable.")
            else:
                self._logger.warning(f"⚠️ Failed to chmod {filename}")
