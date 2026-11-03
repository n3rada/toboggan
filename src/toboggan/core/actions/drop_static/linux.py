# toboggan/core/actions/drop_static/linux.py

# Built-in imports
import posixpath

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.actions.drop_bin.linux import DropBinary
from toboggan.core.utils.binaries import BinaryFetcher


class DropStaticBinary(BaseAction):
    DESCRIPTION = (
        "Fetch, verify, drop, and register one supported static binary: "
        f"{BinaryFetcher.list_available()}."
    )

    def run(self, name: str = None, remote_path: str = None) -> bool:
        if not name:
            logger.warning("No binary name provided.")
            logger.info("Available static binaries:")
            for binary in BinaryFetcher.list_available():
                print(f"  • {binary}")
            return False

        name = name.lower()
        if name not in BinaryFetcher.list_available():
            logger.error(f"Unknown static binary: {name}")
            return False
        arch = self._executor.target.architecture
        if not arch:
            logger.error("Cannot select a static binary for an unknown architecture.")
            return False
        logger.info(f"Preparing static {name} for linux/{arch}.")

        try:
            fetcher = BinaryFetcher(os_name=self._executor.target.os, arch=arch)
            local_path = fetcher.get(name)
        except Exception as exc:
            logger.error(f"Failed to fetch binary: {exc}")
            return False

        if not local_path or not local_path.is_file():
            logger.error("Binary download failed or path invalid.")
            return False

        if not remote_path:
            remote_path = f"{self._executor.working_directory}/{name}"
        elif not posixpath.isabs(remote_path):
            remote_path = posixpath.join(self._executor.target.pwd, remote_path)

        logger.info(f"Uploading {name} from {local_path} to: {remote_path}")
        if not DropBinary(self._executor).run(
            local_path=str(local_path), remote_path=remote_path
        ):
            return False

        if name == "busybox":
            if not self._os_helper.register_busybox(remote_path):
                logger.warning(f"BusyBox dropped but could not be registered: {remote_path}")
                return False
        else:
            self._os_helper.register_command(name, remote_path)
        logger.success(f"Static binary registered: {name} -> {remote_path}")
        return True
