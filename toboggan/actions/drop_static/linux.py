from toboggan.core.action import BaseAction
from toboggan.actions.drop_bin.linux import DropBinary
from toboggan.utils.binaries import BinaryFetcher


class DropStaticBinary(BaseAction):
    DESCRIPTION = (
        "📦 Drop a prebuilt static binary (e.g., curl, kubectl) to the target."
    )

    def run(self, name: str = None, remote_path: str = None) -> None:
        if not name:
            self._logger.error("❌ You must provide a binary name (e.g. curl).")
            return

        os = self._executor.target.os.lower()
        arch = self._executor.target.architecture or "x86_64"

        try:
            fetcher = BinaryFetcher(os=os, arch=arch)
            local_path = fetcher.get(name)
        except Exception as e:
            self._logger.error(f"❌ Failed to fetch binary: {e}")
            return

        DropBinary(self._executor).run(
            local_path=str(local_path),
            remote_path=remote_path,
        )
